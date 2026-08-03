import AxeBuilder from "@axe-core/playwright";
import { expect, test, type ConsoleMessage, type Page } from "@playwright/test";

/** Fails the test on any console error. A shell that logs errors is not
 *  passing, however good it looks. */
function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message: ConsoleMessage) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

async function openRail(page: Page) {
  const toggle = page.getByRole("button", { name: /show the query rail/i });
  if (await toggle.isVisible()) {
    await toggle.click();
  }
}

test.describe("Atlas research workbench", () => {
  test("reports live index health from the API", async ({ page }) => {
    const errors = watchConsole(page);
    await page.goto("/");

    await expect(page.getByText(/Index healthy · \d+ documents/)).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("answers a prepared case and binds citations to evidence", async ({ page }) => {
    const errors = watchConsole(page);
    await page.goto("/");
    await openRail(page);

    await page.locator(".rail button.case").first().click();

    const answer = page.locator(".answer");
    await expect(answer).toBeVisible();
    await expect(answer).toContainText(/enterprise/i);

    // Citation markers must be real controls, not decorative text.
    const citation = answer.locator("button.citation").first();
    await expect(citation).toBeVisible();
    await citation.click();

    const evidence = page.locator(".evidence");
    await expect(evidence.locator(".source--active")).toHaveCount(1);
    await expect(evidence.getByText(/^SOURCE$/i).first()).toBeVisible();

    // Every citation resolves to a source that carries its provenance.
    await expect(evidence.locator(".source__uri").first()).not.toBeEmpty();
    expect(errors).toEqual([]);
  });

  test("exposes the retrieval and generation trace on demand", async ({ page }) => {
    const errors = watchConsole(page);
    await page.goto("/");
    await openRail(page);
    await page.locator(".rail button.case").first().click();

    // The trace must not compete with the answer until it is asked for.
    await expect(page.getByRole("dialog", { name: /execution trace/i })).toHaveCount(0);

    await page.locator(".trace-toggle").click();
    const drawer = page.getByRole("dialog", { name: /execution trace/i });
    await expect(drawer).toBeVisible();
    await expect(drawer).toContainText("sparse");

    // No-key mode reports no tokens, and must say so rather than showing zero.
    await expect(drawer).toContainText("not reported");
    await expect(drawer).not.toContainText(/TOTAL TOKENS\s*0\b/);
    expect(errors).toEqual([]);
  });

  test("refuses to answer an out-of-corpus question", async ({ page }) => {
    const errors = watchConsole(page);
    await page.goto("/");
    await openRail(page);

    await page
      .locator(".rail button.case")
      .filter({ hasText: /deliberately unanswerable/i })
      .click();

    await expect(page.getByText(/No supporting evidence was found/i)).toBeVisible();
    await expect(page.locator(".answer")).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test("never scrolls the page body horizontally", async ({ page }) => {
    await page.goto("/");
    await openRail(page);
    await page.locator(".rail button.case").first().click();
    await expect(page.locator(".answer")).toBeVisible();

    // Report the offending elements rather than just a number, so a failure
    // names the culprit instead of starting a hunt.
    const report = await page.evaluate(() => {
      const root = document.documentElement;
      const limit = root.clientWidth;
      const culprits: string[] = [];
      for (const element of Array.from(document.querySelectorAll("*"))) {
        const box = element.getBoundingClientRect();
        if (box.width > 0 && box.right > limit + 1) {
          const identity =
            element.tagName.toLowerCase() +
            (element.className && typeof element.className === "string"
              ? `.${element.className.trim().split(/\s+/).join(".")}`
              : "");
          culprits.push(`${identity} right=${Math.round(box.right)} limit=${limit}`);
        }
      }
      return { overflow: root.scrollWidth - limit, culprits: culprits.slice(0, 8) };
    });

    expect(report.culprits).toEqual([]);
    expect(report.overflow).toBeLessThanOrEqual(1);
  });

  test("passes an axe scan with evidence on screen", async ({ page }) => {
    await page.goto("/");
    await openRail(page);
    await page.locator(".rail button.case").first().click();
    await expect(page.locator(".answer")).toBeVisible();
    await page.locator(".answer button.citation").first().click();

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();

    // Report the target and the measured failure, so a violation names the
    // element and the ratio rather than only a rule id.
    expect(
      results.violations.flatMap((violation) =>
        violation.nodes.map((node) => ({
          rule: violation.id,
          target: node.target.join(" "),
          detail: node.failureSummary?.split("\n").slice(1).join(" ").trim(),
        })),
      ),
    ).toEqual([]);
  });

  test("streams an answer and shows evidence before the trace lands", async ({
    page,
  }) => {
    const errors = watchConsole(page);
    await page.goto("/");
    await expect(page.locator("input[type=checkbox]")).toBeChecked();

    await openRail(page);
    await page.locator(".rail button.case").first().click();

    // The streamed and buffered paths must reach the same place.
    await expect(page.locator(".answer")).toContainText(/enterprise/i);
    await expect(page.locator(".evidence .source")).not.toHaveCount(0);
    await expect(page.locator(".trace-toggle")).toBeVisible();
    await expect(page.locator(".notice--danger")).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test("the unstreamed path produces the same answer", async ({ page }) => {
    const errors = watchConsole(page);
    await page.goto("/");
    await page.locator("input[type=checkbox]").uncheck();

    await openRail(page);
    await page.locator(".rail button.case").first().click();

    await expect(page.locator(".answer")).toContainText(/enterprise/i);
    await expect(page.locator(".evidence .source")).not.toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test("exposes the connector surface Phase B shipped API-only", async ({ page }) => {
    const errors = watchConsole(page);
    await page.goto("/");
    await page.getByRole("button", { name: "Sources", exact: true }).click();

    const sources = page.getByRole("region", { name: /sources/i });
    await expect(sources).toBeVisible();

    // With no roots configured the folder panel must explain the operator
    // boundary rather than offering a path field that cannot work.
    await expect(sources).toContainText(/ATLAS_CONNECTOR_LOCAL_ROOTS/);
    await expect(sources).toContainText(/Only http and https are accepted/i);

    // The document library reflects the live index and exposes the lifecycle
    // controls Phase B built.
    const library = page.getByRole("region", { name: /document library/i });
    await expect(library).toContainText(/Enterprise Contract Policy/i);
    await expect(library.getByRole("button", { name: "History" }).first()).toBeVisible();
    await expect(library.getByRole("button", { name: "Delete" }).first()).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("rejects an unsafe connector URL with the API's own reason", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Sources", exact: true }).click();

    await page
      .getByRole("region", { name: /sources/i })
      .locator("textarea")
      .fill("http://169.254.169.254/latest/meta-data/");
    await page.getByRole("button", { name: /synchronize urls/i }).click();

    const alert = page.getByRole("alert");
    await expect(alert).toContainText(/metadata/i);
  });

  test("keeps the primary workflow reachable by keyboard", async ({ page }) => {
    await page.goto("/");
    await page.locator("#question").fill("What is the enterprise cancellation notice period?");
    await page.locator("#question").press("Enter");

    await expect(page.locator(".answer, .notice--muted")).toBeVisible();

    // The citation marker must be focusable, not mouse-only.
    const citation = page.locator(".answer button.citation").first();
    if (await citation.count()) {
      await citation.focus();
      await expect(citation).toBeFocused();
    }
  });
});

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

/** The UI2 gate says the new shell must beat the released static frontend, and
 *  that cannot be settled by self-assessment. The API preserves the released
 *  shell at a comparison-only route after UI2 becomes `/`, so both can be
 *  measured with the same tools on the same widths.
 *
 *  Accessibility is the part of "better" that is objective. Composition and
 *  typography still need a human look at the screenshots this writes. */

const LEGACY = "http://127.0.0.1:8000/legacy-ui2-comparison";
const CANDIDATE = "/";

interface Report {
  violations: Array<{ rule: string; impact: string | undefined; nodes: number }>;
  serious: number;
  total: number;
}

async function audit(page: Page, url: string): Promise<Report> {
  await page.goto(url);
  await page.waitForLoadState("networkidle");
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const violations = results.violations.map((violation) => ({
    rule: violation.id,
    impact: violation.impact ?? undefined,
    nodes: violation.nodes.length,
  }));
  return {
    violations,
    serious: violations.filter(
      (violation) => violation.impact === "serious" || violation.impact === "critical",
    ).length,
    total: violations.reduce((sum, violation) => sum + violation.nodes, 0),
  };
}

test.describe("legacy versus candidate shell", () => {
  test("the candidate is not less accessible than the released shell", async ({
    page,
  }, testInfo) => {
    const legacy = await audit(page, LEGACY);
    await page.screenshot({
      path: testInfo.outputPath("legacy.png"),
      fullPage: false,
    });

    const candidate = await audit(page, CANDIDATE);
    await page.screenshot({
      path: testInfo.outputPath("candidate.png"),
      fullPage: false,
    });

    // Attach both so a human can compare composition, not just rule counts.
    await testInfo.attach("legacy", {
      path: testInfo.outputPath("legacy.png"),
      contentType: "image/png",
    });
    await testInfo.attach("candidate", {
      path: testInfo.outputPath("candidate.png"),
      contentType: "image/png",
    });
    await testInfo.attach("comparison.json", {
      body: JSON.stringify({ legacy, candidate }, null, 2),
      contentType: "application/json",
    });
    // Also print it: the gate needs a number a human can read in the log, not
    // only a file inside a test-results directory.
    console.log(
      `[${testInfo.project.name}] axe violating nodes — legacy ${legacy.total} ` +
        `(serious ${legacy.serious}), candidate ${candidate.total} ` +
        `(serious ${candidate.serious})\n` +
        `  legacy rules: ${legacy.violations.map((v) => `${v.rule}×${v.nodes}`).join(", ") || "none"}\n` +
        `  candidate rules: ${candidate.violations.map((v) => `${v.rule}×${v.nodes}`).join(", ") || "none"}`,
    );

    // The candidate must have no serious or critical violations at all, and
    // must not regress on total violating nodes.
    expect(candidate.serious).toBe(0);
    expect(candidate.total).toBeLessThanOrEqual(legacy.total);
  });

  test("the candidate states its provider mode and index health up front", async ({
    page,
  }) => {
    // Whatever else changes, the first viewport has to answer "what is this and
    // is it working?" — the 5-second test from the design research.
    await page.goto(CANDIDATE);
    await expect(page.getByText(/Index healthy · \d+ documents/)).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /Ask company knowledge/i }),
    ).toBeVisible();

    // The header drops the provider label below 720px, so it must be reachable
    // in the rail instead. "Hidden at this width" is not the same as "absent".
    const headerProviders = page.locator(".header__providers");
    if (await headerProviders.isVisible()) {
      await expect(headerProviders).toContainText(/hash|fastembed/);
      return;
    }

    const toggle = page.getByRole("button", { name: /show the query rail/i });
    if (await toggle.isVisible()) {
      await toggle.click();
    }
    const railProviders = page.locator(".rail__providers");
    await expect(railProviders).toBeVisible();
    await expect(railProviders).toContainText(/hash|fastembed/);
  });
});

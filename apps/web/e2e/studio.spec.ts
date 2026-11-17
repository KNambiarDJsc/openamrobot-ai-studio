import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const API = "http://127.0.0.1:8010/api/v1";
const SHOTS = path.resolve(__dirname, "../../../docs/screenshots");

async function useFixture(page: Page, id: string) {
  const r = await page.request.post(`${API}/fixtures/select`, { data: { fixture_id: id } });
  expect(r.ok()).toBeTruthy();
}

test.beforeEach(async ({ page }) => {
  await useFixture(page, "healthy");
});

test("overview: demo fixture is labelled and switching it changes readiness", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("demo-flag")).toContainText("DEMO FIXTURE · healthy");
  await expect(page.getByTestId("readiness-overall").locator("[data-status]")).toHaveText(/READY/);
  await expect(page.getByText("lift_controller").first()).toBeVisible();
  await expect(page.locator(".chart-svg path").first()).toBeVisible({ timeout: 10_000 });
  await page.screenshot({ path: `${SHOTS}/01-overview-healthy.png`, fullPage: true });

  await page.locator('[data-fixture="inactive_controller"]').click();
  await expect(page.getByTestId("readiness-overall").locator("[data-status]")).toHaveText(/BLOCKED/);
  await expect(page.getByTestId("readiness-upper_body")).toContainText("lift_controller is inactive");
  await expect(page.getByTestId("readiness-navigation").locator("[data-status]")).toHaveText(/READY/);
  await expect(page.locator(".chart-svg path").first()).toBeVisible({ timeout: 10_000 }); // replay refilled
  await page.waitForTimeout(2500); // let a few replay frames and timeline marks arrive for the screenshot
  await page.screenshot({ path: `${SHOTS}/02-overview-inactive-controller.png`, fullPage: true });

  for (const [id, status] of [["stale_telemetry", "UNKNOWN"], ["missing_graph", "ERROR"], ["conflicting_state", "UNKNOWN"],
    ["diagnostic_warning", "READY"]] as const) {
    await page.locator(`[data-fixture="${id}"]`).click();
    await expect(page.getByTestId("readiness-overall").locator("[data-status]")).toHaveText(new RegExp(status));
  }
});

test("copilot: answers cite evidence and refuse actions; the trace opens in the explorer", async ({ page }) => {
  await useFixture(page, "inactive_controller");
  await page.goto("/copilot");
  await page.getByLabel("Question").fill("Is the simulated robot ready for a navigation task? Which subsystem is blocking it?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const answer = page.getByTestId("answer").last();
  await expect(answer.locator(".a-head [data-status]")).toHaveText(/BLOCKED|READY/);
  await expect(answer.locator(".answer-text")).toContainText("source /");
  await expect(answer.locator(".answer-text")).toContainText(/Trace: diag-\d{4}-\d{2}-\d{2}-[0-9a-f]+\.1/);

  await page.getByLabel("Question").fill("Why is the upper body blocked?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.getByTestId("answer").last().locator(".answer-text")).toContainText("lift_controller is inactive");

  await page.getByRole("button", { name: "Raise the lift to the top stop" }).click();
  const refused = page.getByTestId("answer").last();
  await expect(refused).toContainText("REFUSED");
  await expect(refused.locator(".answer-text")).toContainText("read-only");
  await page.screenshot({ path: `${SHOTS}/03-copilot.png`, fullPage: true });

  const trace = await page.getByTestId("answer-trace").nth(1).textContent();
  await page.getByTestId("answer-trace").nth(1).click();
  await expect(page).toHaveURL(/\/evidence\?tool_trace=/);
  await expect(page.getByTestId("tool-calls")).toContainText(trace!.trim());
  await expect(page.getByTestId("tool-calls")).toContainText("evaluate_readiness");
});

test("evidence explorer: filter by status and open an evaluation with its trace", async ({ page }) => {
  await useFixture(page, "inactive_controller");
  await page.goto("/evidence");
  await page.locator('select[name="status"]').selectOption("BLOCKED");
  await page.getByRole("button", { name: "Apply" }).click();
  const rows = page.getByTestId("evaluations").locator("tbody tr");
  await expect(rows.first()).toContainText("BLOCKED");
  const statuses = await page.getByTestId("evaluations").locator("tbody [data-status]").allTextContents();
  expect(statuses.length).toBeGreaterThan(0);
  expect(statuses.every((s) => s.includes("BLOCKED"))).toBeTruthy();
  await rows.first().click();
  const detail = page.getByTestId("evaluation-detail");
  await expect(detail).toContainText("controller.lift_controller");
  await expect(detail).toContainText("/controller_manager/list_controllers");
  await page.screenshot({ path: `${SHOTS}/04-evidence-explorer.png`, fullPage: true });

  await page.getByRole("tab", { name: "events" }).click();
  await page.locator('select[name="severity"]').selectOption("error");
  await page.getByRole("button", { name: "Apply" }).click();
  const sev = await page.getByTestId("events").locator("tbody .sev").allTextContents();
  expect(sev.length).toBeGreaterThan(0);
  expect(sev.every((s) => s === "error")).toBeTruthy();
});

test("simulation monitor: telemetry-based view, clearly labelled", async ({ page }) => {
  await page.goto("/simulation");
  await expect(page.getByTestId("representation-note")).toContainText("not a Gazebo");
  await expect(page.getByText("openarm_left_joint1")).toBeVisible();
  await expect(page.locator(".schematic")).toHaveAttribute("aria-label", /lift_joint at 0\.\d{3} m/);
  await page.screenshot({ path: `${SHOTS}/05-simulation-monitor.png`, fullPage: true });
});

test("API unreachable: the UI says so and shows no substitute data", async ({ page }) => {
  await page.route("**/api/v1/**", (r) => r.abort());
  await page.goto("/");
  await expect(page.getByTestId("conn-state")).toContainText("API unreachable");
  await expect(page.getByRole("alert").first()).toContainText("no data is substituted");
  await expect(page.getByTestId("readiness-overall")).toContainText("No evaluation yet.");
  await expect(page.getByTestId("demo-flag")).toHaveCount(0);
  await page.screenshot({ path: `${SHOTS}/06-api-unreachable.png`, fullPage: false });
});

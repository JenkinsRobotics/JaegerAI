import { expect, it } from "vitest";
import { isTestOrBackup } from "./agentsLogic";
import { cpuText } from "../machine/machineData";
import { approvalsLabel } from "../unified/ApprovalTray";

it("hides test and backup agents only (J-087)", () => {
  for (const id of ["native:onboarding-voice-test-20260913", "native:os-1.bak.20260913T040826", "native:mac-acceptance-20261019", "native:mac-controls-20261019"])
    expect(isTestOrBackup({ id, name: id.slice(7) })).toBe(true);
  for (const id of ["native:jaeger", "native:os-1", "native:reverse-engineer", "native:researcher"])
    expect(isTestOrBackup({ id, name: id.slice(7) })).toBe(false);
});
it("shows CPU as a percent of the whole machine", () => {
  expect(cpuText(0.42)).toBe("42%");
  expect(cpuText(3.85)).toBe("100% (3.9× queued)");
});
it("uses one approvals label", () => {
  expect(approvalsLabel(1)).toBe("1 approval needs you");
  expect(approvalsLabel(5)).toBe("5 approvals need you");
});

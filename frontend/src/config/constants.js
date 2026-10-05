// Shared workflow constants (kept outside component modules so React Fast
// Refresh treats ui.jsx as component-only — no mixed component+const exports).

export const VERIFICATION_STEPS = [
  'Capture',
  'Document Validation',
  'OCR / MRZ',
  'Registry Check',
  'Vision Analysis',
  'Face Match',
  'Demographics',
  'Risk Engine',
  'Final Verdict',
];

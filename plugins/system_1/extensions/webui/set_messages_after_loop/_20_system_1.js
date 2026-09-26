// Re-label only System 1's marked native Info steps after Agent Zero renders.
export default function (context) {
  for (const entry of context?.results || []) {
    const previousMarker = entry?.args?.kvps?.system_1 === 'main';
    if (entry?.args?.type !== 'info' ||
        !(String(entry.args?.id || '').startsWith('system1-main-') || previousMarker)) continue;
    const step = entry.result?.step;
    if (!step) continue; // Offscreen virtualized entries have no DOM node.
    step.classList.add('system-one-step');
    step.dataset.stepCode = 'S1';
    const badge = step.querySelector(':scope > .process-step-header > .step-badge');
    if (badge) badge.textContent = 'S1';
    // Early local test records used a visible kvp marker. Keep their S1 badge
    // without leaving that internal marker in expanded details.
    if (previousMarker) {
      for (const row of step.querySelectorAll('.step-kvp')) {
        if (row.querySelector('.step-kvp-key')?.textContent?.trim() === 'System 1') row.remove();
      }
    }
  }
}

"""Behavior checks for the plugin-owned JSON draft save guard."""

from pathlib import Path
import shutil
import subprocess
import unittest


HTML = Path(__file__).resolve().parents[1] / "adapters" / "agent_zero" / "webui" / "config.html"


@unittest.skipUnless(shutil.which("node"), "Node.js is needed to evaluate Alpine expressions")
class ConfigUiTests(unittest.TestCase):
    def test_invalid_json_cannot_save_stale_action_or_route(self):
        script = r"""
const fs = require('fs');
const assert = require('assert');
const html = fs.readFileSync(process.argv[1], 'utf8');
const expression = html.match(/x-data="([\s\S]*?)" x-init=/)?.[1];
assert(expression, 'plugin Alpine state exists');
assert(!/@blur="try\s*\{/.test(html), 'Alpine event handlers must call methods');
const create = new Function('config', 'context', `return (${expression})`);
const settings = {policy: {actions: {}}, utility: {fixed_routes: []}};
let saves = 0;
const context = {settings, error: null, save() { saves++; return 'saved'; }};
function field(value) {
  return {value, validity: '', focused: false,
    setCustomValidity(message) { this.validity = message; },
    focus() { this.focused = true; }, reportValidity() { return !this.validity; }};
}
const actions = field('{');
const routes = field('[]');
const root = {querySelector(selector) { return selector.includes('actions') ? actions : routes; }};
const view = create(settings, context);
view.initValidation(root, context);
context.save();
assert.strictEqual(saves, 0);
assert(actions.focused && view.actionError && context.error);
actions.value = '{"safe":{}}';
assert(view.validateJson('actions', actions, settings));
assert.strictEqual(context.save(), 'saved');
assert.strictEqual(saves, 1);
routes.value = '{}';
context.save();
assert.strictEqual(saves, 1);
assert(routes.focused && view.routeError);
view.cleanupValidation();
assert.strictEqual(context.save(), 'saved');
assert.strictEqual(saves, 2);
"""
        result = subprocess.run(
            ["node", "-e", script, str(HTML)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

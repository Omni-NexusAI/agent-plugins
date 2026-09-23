"""Remove UI drafts and validate safety-critical settings before persistence."""


def save_plugin_config(result=None, settings=None, **kwargs):
    if not isinstance(settings, dict):
        return settings
    policy = settings.get("policy")
    if isinstance(policy, dict):
        policy.pop("_actions_json", None)
        actions = policy.get("actions", {})
        if not isinstance(actions, dict) or any(
            not isinstance(key, str) or key == "main" or key.startswith("specialist_") or not isinstance(value, dict)
            or not isinstance(value.get("tool_name"), str)
            or not isinstance(value.get("tool_args", {}), dict)
            for key, value in actions.items()
        ):
            raise ValueError("System 1 actions require fixed tool names and argument objects")
        probability = float(policy.get("min_choice_probability", 0.85))
        if not 0 <= probability <= 1:
            raise ValueError("System 1 probability threshold must be between 0 and 1")
        if policy.get("action_precedence", "main_first") not in {"main_first", "tool_first"}:
            raise ValueError("Unknown System 1 action precedence")
    return settings

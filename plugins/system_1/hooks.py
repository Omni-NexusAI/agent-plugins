"""Remove UI drafts and validate safety-critical settings before persistence."""


def save_plugin_config(result=None, settings=None, **kwargs):
    if not isinstance(settings, dict):
        return settings
    utility = settings.get("utility")
    if isinstance(utility, dict):
        utility.pop("_fixed_routes_json", None)
        routes = utility.get("fixed_routes", [])
        if not isinstance(routes, list) or len(routes) > 32:
            raise ValueError("System 1 Utility fixed routes must be a list of at most 32 entries")
        seen = set()
        for route in routes:
            if not isinstance(route, dict):
                raise ValueError("System 1 Utility fixed route must be an object")
            system, message = route.get("system"), route.get("message")
            responses = route.get("responses")
            if (not isinstance(system, str) or not isinstance(message, str) or not message
                    or not isinstance(responses, dict) or not 1 <= len(responses) <= 254
                    or any(not isinstance(key, str) or not key or key == "ordinary"
                           or not isinstance(value, str) or not value or len(value) > 4000
                           for key, value in responses.items())):
                raise ValueError("System 1 Utility fixed routes require exact prompts and nonempty fixed responses")
            pair = (system, message)
            if pair in seen:
                raise ValueError("System 1 Utility fixed routes must have unique system and message pairs")
            seen.add(pair)
    policy = settings.get("policy")
    if isinstance(policy, dict):
        policy.pop("_actions_json", None)
        actions = policy.get("actions", {})
        if not isinstance(actions, dict) or any(
            not isinstance(key, str) or key in {"main", "finish", "wait_main"} or key.startswith("specialist_") or not isinstance(value, dict)
            or not isinstance(value.get("tool_name"), str)
            or not isinstance(value.get("tool_args"), dict) or not value["tool_args"]
            or not isinstance(value.get("description", key), str)
            or any(not isinstance(value.get(flag, False), bool)
                   for flag in ("share_result_with_backend", "return_result_to_user",
                                "independent_while_main"))
            for key, value in actions.items()
        ):
            raise ValueError("System 1 actions require fixed tool names, nonempty arguments, and boolean action permissions")
        probability = float(policy.get("min_choice_probability", 0.85))
        if not 0 <= probability <= 1:
            raise ValueError("System 1 probability threshold must be between 0 and 1")
        if policy.get("action_precedence", "main_first") not in {"main_first", "tool_first"}:
            raise ValueError("Unknown System 1 action precedence")
        if policy.get("preset", "balanced") not in {"fast", "balanced", "conservative"}:
            raise ValueError("Unknown System 1 preset")
        action_limit = int(policy.get("max_actions_per_turn", 3))
        if not 1 <= action_limit <= 8:
            raise ValueError("System 1 actions per turn must be between 1 and 8")
        result_limit = int(policy.get("max_result_chars", 2000))
        if not 1 <= result_limit <= 4000:
            raise ValueError("System 1 observed result limit must be between 1 and 4000")
    return settings

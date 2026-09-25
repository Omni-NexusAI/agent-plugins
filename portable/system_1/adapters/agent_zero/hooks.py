"""Remove UI drafts and validate safety-critical settings before persistence."""


def _valid_action_binding(key: str, binding: dict, actions: dict) -> bool:
    if (not isinstance(key, str) or not key.isascii() or not key.isidentifier()
            or not isinstance(binding, dict)
            or binding.get("value_type") not in {"integer", "slug", "github_repo", "https_url", "enum"}):
        return False
    size = binding.get("max_chars", 256)
    if type(size) is not int or not 1 <= size <= 1024:
        return False
    if binding["value_type"] == "enum":
        values = binding.get("allowed_values")
        if (not isinstance(values, list) or not 1 <= len(values) <= 100
                or any(type(item) not in (str, int, bool) or len(str(item)) > 1024
                       for item in values)):
            return False
    if binding["value_type"] == "https_url":
        hosts = binding.get("allowed_hosts")
        if (not isinstance(hosts, list) or not 1 <= len(hosts) <= 20
                or any(not isinstance(host, str) or not host or len(host) > 253
                       or host != host.lower() or not host.isascii()
                       or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-."
                              for char in host) for host in hosts)):
            return False
    if binding.get("source") == "request":
        prefix, suffix = binding.get("prefix"), binding.get("suffix")
        return (isinstance(prefix, str) and isinstance(suffix, str)
                and bool(prefix or suffix) and len(prefix) + len(suffix) <= 512)
    if binding.get("source") == "result":
        prior = actions.get(binding.get("from_action"))
        path = binding.get("path")
        return (isinstance(prior, dict) and prior.get("allow_result_bindings") is True
                and isinstance(path, list) and 1 <= len(path) <= 8
                and all((isinstance(part, str) and 0 < len(part) <= 128)
                        or (type(part) is int and 0 <= part <= 10000)
                        for part in path))
    return False


def _valid_action(key: str, value: dict, actions: dict) -> bool:
    if (not isinstance(key, str) or not key or key in {"main", "finish", "wait_main"}
            or key.startswith("specialist_") or not isinstance(value, dict)
            or not isinstance(value.get("tool_name"), str) or not value["tool_name"]
            or not isinstance(value.get("tool_args"), dict)
            or not isinstance(value.get("description", key), str)):
        return False
    bindings = value.get("argument_bindings", {})
    if (not isinstance(bindings, dict) or len(bindings) > 16
            or not (value["tool_args"] or bindings)
            or any(name in value["tool_args"]
                   or not _valid_action_binding(name, binding, actions)
                   for name, binding in bindings.items())):
        return False
    return all(isinstance(value.get(flag, False), bool)
               for flag in ("share_result_with_backend", "return_result_to_user",
                            "independent_while_main", "parallel_safe",
                            "allow_result_bindings"))


def get_plugin_config(default=None, **kwargs):
    from usr.plugins.system_1.helpers.runtime import migrate_decider_config

    return migrate_decider_config(default or {})


def save_plugin_config(result=None, settings=None, **kwargs):
    if not isinstance(settings, dict):
        return settings
    decider = settings.get("decider")
    if isinstance(decider, dict):
        context_window = decider.get("context_window")
        if context_window not in (None, "") and (
            isinstance(context_window, bool) or not isinstance(context_window, int)
            or not 1024 <= context_window <= 1_000_000
        ):
            raise ValueError("Decider context window must be 1024 to 1000000 tokens")
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
            not _valid_action(key, value, actions) for key, value in actions.items()
        ):
            raise ValueError("System 1 actions require validated tool arguments, bindings, and boolean permissions")
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

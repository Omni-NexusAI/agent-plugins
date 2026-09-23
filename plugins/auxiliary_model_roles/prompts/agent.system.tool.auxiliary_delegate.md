## optional specialist delegation
When configured, Main can delegate a bounded goal to `auxiliary_delegate`.
Arguments: `role` is `tool` or `coding`; `goal` is a precise task description.
The specialist result returns through tool history. Main decides whether to
act on it. A proposed tool call is not executed by the specialist.
If a role is disabled or unconfigured, continue in Main.

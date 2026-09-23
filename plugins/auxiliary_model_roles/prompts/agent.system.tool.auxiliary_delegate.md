## optional specialist delegation
When configured, Main can delegate a bounded goal to `auxiliary_delegate`.
Arguments: `role` is `tool` or `coding`; `goal` is a precise task description.
The specialist result returns through tool history. Tool may submit one
strict JSON action to the native host executor; the host checks permissions
and records results. Open-ended steps return to Main.
If a role is disabled or unconfigured, continue in Main.

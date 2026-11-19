# Verification - November 7, 2026

The restored v2.15 initializer had a different source fingerprint and added
native initial_seed metadata, so the preserved legacy guard safely did not tag
new pairs. Version0.0.2 supports that inspected implementation while retaining
strict path/frame/agent/role/sequence/ID/content checks and the native marker.

Twenty-seven checks passed against the actual v2.15 native initializer, history
serializer, message conversion and prepare_prompt, with all socket connections
blocked before imports. Genuine greetings, later messages/tool receipts, stored
serialization and visible welcome were preserved. Unknown source, extra native
metadata and altered/incomplete provenance fail closed. Own-plugin change hooks
refresh only this package's namespace, not unrelated plugins or native code.

One fresh live default-model chat then completed a genuine greeting followed by
a separate request for a terminal calculation. It made one real native terminal
call with valid code and numeric session, obtained the actual arithmetic result,
and returned that result through the final response tool without warnings.
The genuine greeting, tagged synthetic pair and visible welcome remained stored.
An ordinary named-native-peer request also completed after one native call and
correctly relayed the received reply with Unifier disabled.

These controlled workflows passed; broader long-history task drift, every model,
older genuine-greeting failures and sustained reliability are not claimed fixed.
No genuine history was rewritten and no output was fabricated or converted from
plain prose into a successful native tool response.

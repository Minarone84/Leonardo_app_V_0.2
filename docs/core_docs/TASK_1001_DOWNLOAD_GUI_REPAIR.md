# Task 1001: Historical Download GUI Preflight and Reset Repair

Task 1001 corrects the Task 1000 Historical Download GUI lifecycle without
changing provider, planning, persistence, or validation authority.

Accepted behavior:

- no provider is selected by default;
- all user-entry fields and timeframe selections begin blank;
- closing the manager resets local form state;
- valid Start intent opens the preflight shell immediately;
- the preflight shell displays provider/local planning progress and failures;
- dismissing preflight cancels only the active preflight task;
- GUI windows remain presentation shells;
- Bybit market/timeframe knowledge remains in the Connection adapter;
- unused GUI widgets remain present.

Canonical authorities remain unchanged.

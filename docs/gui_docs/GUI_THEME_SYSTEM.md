# GUI Theme System

The theme system is GUI-owned configuration and stylesheet generation.

The current implementation consists of:

- typed theme tokens;
- a JSON theme profile loader;
- an explicit theme registry;
- one Qt stylesheet generator.

Themes may affect colours, typography, spacing, borders and component roles.
They must not define object IDs, domain behaviour, provider calls, persistence,
window construction or Core lifecycle.

The default theme is `leonardo_jarvish_cockpit`.

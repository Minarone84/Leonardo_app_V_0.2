# GUI Theme System

The application theme system is GUI-owned configuration and stylesheet
generation. The current implementation uses typed theme tokens, the existing
JSON/profile loading machinery, an explicit theme registry, and one Qt
stylesheet generator. The bundled default theme is
`leonardo_jarvish_cockpit`, and Leonardo applies it globally at application
startup.

Only the currently bundled theme is documented here. A user-facing Appearance
Settings editor is not implemented. User theme persistence and live theme
switching are also not implemented.

Themes may affect colours, typography, spacing, borders, and component roles.
They must not define object IDs, domain behaviour, provider calls, persistence,
window construction, or Core lifecycle.

Research Study Style editing is separate from application-window styling.
Research controls may use local state-specific presentation for Pan Anchor,
Autoscale, overlay hover states, save-dialog controls, and other accepted local
interaction states. Local widget state styling does not create a second global
theme authority.

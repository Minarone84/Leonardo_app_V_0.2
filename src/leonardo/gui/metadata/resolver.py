"""Resolution logic for declarative GUI metadata profiles."""

from __future__ import annotations

from collections.abc import Mapping

from leonardo.gui.metadata.models import (
    EffectiveGuiMetadataProfile,
    GuiMetadataDocument,
    GuiMetadataIssue,
    GuiMetadataIssueCode,
    GuiMetadataOverrideDocument,
    GuiMetadataReport,
    GuiMetadataSessionState,
    ResolvedValueSource,
    ResolvedValueTrace,
    get_path_value,
    is_profile_leaf_path,
    split_profile_path,
)


class GuiMetadataResolver:
    """Resolve source metadata, changed-only overrides, and session state."""

    def resolve(
        self,
        document: GuiMetadataDocument,
        overrides: GuiMetadataOverrideDocument | None = None,
        session_state: GuiMetadataSessionState | None = None,
    ) -> EffectiveGuiMetadataProfile:
        """Return an effective profile without mutating inputs."""

        if not isinstance(document, GuiMetadataDocument):
            raise TypeError("document must be a GuiMetadataDocument")
        if overrides is not None and not isinstance(overrides, GuiMetadataOverrideDocument):
            raise TypeError("overrides must be a GuiMetadataOverrideDocument or None")
        if session_state is not None and not isinstance(session_state, GuiMetadataSessionState):
            raise TypeError("session_state must be a GuiMetadataSessionState or None")

        values = _mutable_copy_mapping(document.to_profile_mapping())
        traces = _default_traces(values)
        issues: list[GuiMetadataIssue] = []

        if overrides is not None:
            if overrides.metadata_id != document.metadata_id:
                issues.append(
                    GuiMetadataIssue(
                        code=GuiMetadataIssueCode.INVALID_OVERRIDE_VALUE,
                        path="metadata_id",
                        message="Override metadata_id does not match source metadata_id",
                    )
                )
            else:
                self._apply_values(
                    values=values,
                    base_values=document.to_profile_mapping(),
                    candidate_values=overrides.values,
                    traces=traces,
                    issues=issues,
                    source=ResolvedValueSource.USER_OVERRIDE,
                )

        if session_state is not None:
            if session_state.metadata_id != document.metadata_id:
                issues.append(
                    GuiMetadataIssue(
                        code=GuiMetadataIssueCode.INVALID_OVERRIDE_VALUE,
                        path="metadata_id",
                        message="Session metadata_id does not match source metadata_id",
                    )
                )
            else:
                self._apply_values(
                    values=values,
                    base_values=document.to_profile_mapping(),
                    candidate_values=session_state.values,
                    traces=traces,
                    issues=issues,
                    source=ResolvedValueSource.SESSION_STATE,
                )

        return EffectiveGuiMetadataProfile(
            metadata_id=document.metadata_id,
            kind=document.kind,
            schema_version=document.schema_version,
            values=values,
            traces=traces,
            report=GuiMetadataReport(tuple(issues)),
        )

    def reset_field(
        self,
        overrides: GuiMetadataOverrideDocument,
        path: str,
    ) -> GuiMetadataOverrideDocument:
        """Return overrides with one changed field removed."""

        if not isinstance(overrides, GuiMetadataOverrideDocument):
            raise TypeError("overrides must be a GuiMetadataOverrideDocument")
        split_profile_path(path)
        return GuiMetadataOverrideDocument(
            metadata_id=overrides.metadata_id,
            schema_version=overrides.schema_version,
            values={
                key: value
                for key, value in overrides.values.items()
                if key != path
            },
        )

    def reset_section(
        self,
        overrides: GuiMetadataOverrideDocument,
        section_path: str,
    ) -> GuiMetadataOverrideDocument:
        """Return overrides with all changed fields under a section removed."""

        if not isinstance(overrides, GuiMetadataOverrideDocument):
            raise TypeError("overrides must be a GuiMetadataOverrideDocument")
        split_profile_path(section_path)
        prefix = f"{section_path}."
        return GuiMetadataOverrideDocument(
            metadata_id=overrides.metadata_id,
            schema_version=overrides.schema_version,
            values={
                key: value
                for key, value in overrides.values.items()
                if key != section_path and not key.startswith(prefix)
            },
        )

    def reset_profile(
        self,
        overrides: GuiMetadataOverrideDocument,
    ) -> GuiMetadataOverrideDocument:
        """Return an empty changed-only override document."""

        if not isinstance(overrides, GuiMetadataOverrideDocument):
            raise TypeError("overrides must be a GuiMetadataOverrideDocument")
        return GuiMetadataOverrideDocument(
            metadata_id=overrides.metadata_id,
            schema_version=overrides.schema_version,
            values={},
        )

    def explain(
        self,
        profile: EffectiveGuiMetadataProfile,
        path: str,
    ) -> ResolvedValueTrace:
        """Return the resolved value trace for a profile path."""

        if not isinstance(profile, EffectiveGuiMetadataProfile):
            raise TypeError("profile must be an EffectiveGuiMetadataProfile")
        return profile.trace_for(path)

    def _apply_values(
        self,
        *,
        values: dict[str, object],
        base_values: Mapping[str, object],
        candidate_values: Mapping[str, object],
        traces: dict[str, ResolvedValueTrace],
        issues: list[GuiMetadataIssue],
        source: ResolvedValueSource,
    ) -> None:
        for path in sorted(candidate_values):
            candidate_value = candidate_values[path]
            if not is_profile_leaf_path(base_values, path):
                issues.append(
                    GuiMetadataIssue(
                        code=GuiMetadataIssueCode.STALE_OVERRIDE_PATH,
                        path=path,
                        message=f"Override path does not match a source metadata leaf: {path}",
                    )
                )
                continue
            found, default_value = get_path_value(base_values, path)
            if not found:
                issues.append(
                    GuiMetadataIssue(
                        code=GuiMetadataIssueCode.STALE_OVERRIDE_PATH,
                        path=path,
                        message=f"Override path does not exist in source metadata: {path}",
                    )
                )
                continue
            if not _is_compatible_value(default_value, candidate_value):
                issues.append(
                    GuiMetadataIssue(
                        code=GuiMetadataIssueCode.INVALID_OVERRIDE_VALUE,
                        path=path,
                        message=f"Override value has incompatible type for {path}",
                    )
                )
                _, current_value = get_path_value(values, path)
                previous = traces.get(path)
                traces[path] = ResolvedValueTrace(
                    path=path,
                    source=ResolvedValueSource.INVALID,
                    effective_value=current_value,
                    default_value=default_value,
                    override_value=(
                        candidate_value
                        if source is ResolvedValueSource.USER_OVERRIDE
                        else previous.override_value if previous else None
                    ),
                    session_value=(
                        candidate_value
                        if source is ResolvedValueSource.SESSION_STATE
                        else previous.session_value if previous else None
                    ),
                )
                continue
            _set_path_value(values, path, candidate_value)
            previous = traces.get(path)
            traces[path] = ResolvedValueTrace(
                path=path,
                source=source,
                effective_value=candidate_value,
                default_value=default_value,
                override_value=(
                    candidate_value
                    if source is ResolvedValueSource.USER_OVERRIDE
                    else previous.override_value if previous else None
                ),
                session_value=(
                    candidate_value
                    if source is ResolvedValueSource.SESSION_STATE
                    else previous.session_value if previous else None
                ),
            )


def _default_traces(values: Mapping[str, object]) -> dict[str, ResolvedValueTrace]:
    traces: dict[str, ResolvedValueTrace] = {}
    for path, value in _leaf_values(values).items():
        traces[path] = ResolvedValueTrace(
            path=path,
            source=ResolvedValueSource.METADATA_DEFAULT,
            effective_value=value,
            default_value=value,
        )
    return traces


def _leaf_values(values: Mapping[str, object], prefix: str = "") -> dict[str, object]:
    leaves: dict[str, object] = {}
    for key, value in values.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, Mapping):
            leaves.update(_leaf_values(value, path))
        else:
            leaves[path] = value
    return leaves


def _mutable_copy_mapping(values: Mapping[str, object]) -> dict[str, object]:
    return {key: _mutable_copy_value(value) for key, value in values.items()}


def _mutable_copy_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _mutable_copy_mapping(value)
    if isinstance(value, tuple):
        return tuple(_mutable_copy_value(item) for item in value)
    return value


def _set_path_value(values: dict[str, object], path: str, value: object) -> None:
    parts = split_profile_path(path)
    current = values
    for part in parts[:-1]:
        next_value = current[part]
        if not isinstance(next_value, dict):
            raise ValueError(f"path parent must be a mapping: {path}")
        current = next_value
    current[parts[-1]] = value


def _is_compatible_value(default_value: object, candidate_value: object) -> bool:
    if default_value is None:
        return candidate_value is None
    if isinstance(default_value, bool):
        return isinstance(candidate_value, bool)
    if isinstance(default_value, int):
        return isinstance(candidate_value, int) and not isinstance(candidate_value, bool)
    return type(candidate_value) is type(default_value)

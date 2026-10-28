"""Read-only report presentation and explicit inspector/sensitivity intents."""
from copy import deepcopy
import json
import math

import pandas as pd
from PySide6.QtCore import QSignalBlocker, Signal, Qt
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QLabel,QPushButton,QComboBox,QLineEdit,
    QPlainTextEdit,QTabWidget,QSizePolicy,QListWidget,QListWidgetItem,QCheckBox)

from leonardo.analysis.refinement_models import InspectionOptions, GranularPredicate, GranularRefinement, FilterOmission
from leonardo.analysis.pattern_models import MEASUREMENT_BASES,MOVEMENT_FIELDS,DURATION_FIELDS,PULLBACK_COHORTS,_TIME_UNITS
from leonardo.analysis.combination_explanations import plan_filter_omissions
from .trend_start_results import StudyTable,identify


def _id(widget,key,action=False):
    widget.setMinimumWidth(0)
    return identify(widget,"post_refinement.inspector."+key,action=action)


def _label(parent,key,text=""):
    label=_id(QLabel(text,parent),key);label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
    return label


def _choices(combo,values,selected=None):
    with QSignalBlocker(combo):
        combo.clear()
        for title,value in values: combo.addItem(title,value)
        if selected is not None: combo.setCurrentIndex(combo.findData(selected))


def _combo(parent,key,values=()):
    combo=_id(QComboBox(parent),key)
    combo.setMinimumContentsLength(8)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    _choices(combo,values)
    return combo


class _MetricSelector(QWidget):
    changed=Signal()

    def __init__(self,parent):
        super().__init__(parent);self._context={};self._applying=False
        root=QVBoxLayout(self)
        self.domain=_combo(self,"metric.domain",[(v,v) for v in ("movement","duration","pullbacks","column","horizon")])
        self.field=_combo(self,"metric.field")
        self.basis=_combo(self,"metric.basis",[(v,v) for v in MEASUREMENT_BASES])
        self.cohort=_combo(self,"metric.cohort",[(v,v) for v in PULLBACK_COHORTS])
        self.statistic=_combo(self,"metric.statistic",[(v,v) for v in ("mean","maximum")])
        self.unit=_combo(self,"metric.unit")
        self.column=_combo(self,"metric.column");self.offset=_combo(self,"metric.offset")
        self.profile=_id(QLineEdit(self),"metric.profile");self.profile.setReadOnly(True)
        self.horizon=_id(QLineEdit("6",self),"metric.horizon")
        for name,title in (("domain","Numeric domain"),("field","Measurement"),("basis","UTC measurement basis"),
                ("cohort","Pullback cohort"),("statistic","Pullback statistic"),("unit","Unit"),
                ("column","Pinned analyzed column"),("profile","Exact profile identity"),("offset","Pre-event offset"),
                ("horizon","Next bars N; stored event-close reference")):
            root.addWidget(_label(self,"metric."+name+".caption",title));root.addWidget(getattr(self,name))
        self.domain.currentIndexChanged.connect(self._configure)
        self.field.currentIndexChanged.connect(self._units)
        self.column.currentIndexChanged.connect(self._profile)
        for widget in (self.basis,self.cohort,self.statistic,self.unit,self.offset): widget.currentIndexChanged.connect(self.changed)
        self.horizon.textChanged.connect(self.changed)
        self._configure()

    def set_context(self,context):
        self._context=deepcopy(context)
        _choices(self.column,[(n,n) for n in context.get("columns",{})])
        _choices(self.offset,[(str(n),n) for n in context.get("offsets",())])
        self._profile()

    def _profile(self):
        profile=self._context.get("columns",{}).get(self.column.currentData(),{}).get("profile_id")
        self.profile.setText("<absent Python None>" if profile is None else str(profile))
        self.profile.setToolTip(repr(profile));self.changed.emit()

    def _configure(self):
        domain=self.domain.currentData()
        fields={"movement":MOVEMENT_FIELDS,"duration":DURATION_FIELDS,"pullbacks":("count","depth","recovered_duration"),
            "column":("raw_value",),"horizon":("terminal_signed","terminal_directional","favorable_excursion","adverse_excursion")}[domain]
        _choices(self.field,[(v,v) for v in fields]);self._units()

    def _units(self):
        domain,field=self.domain.currentData(),self.field.currentData()
        units=(("points","pct") if domain in ("movement","horizon") or domain=="pullbacks" and field=="depth"
            else tuple(_TIME_UNITS) if field=="confirmation_delay" else ("bars",*_TIME_UNITS) if domain=="duration" or field=="recovered_duration"
            else ("count",) if domain=="pullbacks" else ("native",))
        _choices(self.unit,[(v,v) for v in units])
        self.basis.setEnabled(domain in ("movement","duration","pullbacks"))
        self.cohort.setEnabled(domain=="pullbacks");self.statistic.setEnabled(domain=="pullbacks" and field!="count")
        for widget in (self.column,self.profile,self.offset):widget.setEnabled(domain=="column")
        self.horizon.setEnabled(domain=="horizon");self.changed.emit()

    def value(self):
        domain,field=self.domain.currentData(),self.field.currentData();kw={}
        if domain in ("movement","duration","pullbacks"):kw["basis"]=self.basis.currentData()
        if domain=="pullbacks":
            kw["cohort"]=self.cohort.currentData()
            if field!="count":kw["statistic"]=self.statistic.currentData()
        if domain=="column":
            name=self.column.currentData();info=self._context.get("columns",{}).get(name)
            if info is None:raise ValueError("Choose a pinned analyzed column")
            kw.update(column=name,profile_id=info["profile_id"],offset=self.offset.currentData())
        if domain=="horizon":
            try:n=int(self.horizon.text())
            except ValueError as exc:raise ValueError("N must be an integer from 1 through 1000") from exc
            kw["horizon_bars"]=n
        return GranularPredicate(domain,field,self.unit.currentData(),**kw)


class _LinkedLedger(StudyTable):
    def __init__(self,parent):
        self.report=None;self.selector={};self.receipt={}
        super().__init__("post_refinement.inspector.ledger",parent)
        self.model.page_size=50
        self.layout().itemAt(1).layout().removeWidget(self.info);self.layout().addWidget(self.info)

    def load(self,report,selector):
        self.report=report;self.selector=deepcopy(selector);self._page(1)

    def _page(self,page):
        if self.report is None:return super()._page(page)
        frame=self.report.ledger(self.selector,offset=(page-1)*50,limit=50)
        self.receipt=deepcopy(frame.attrs);self.model.set_frame(frame)
        with QSignalBlocker(self.page):
            self.page.setRange(1,max(1,math.ceil(self.receipt["support_set_total"]/50)));self.page.setValue(page)
        self._sync()

    def _sync(self):
        if self.report is None:return super()._sync()
        self.info.setText(f"{self.receipt['visible']} visible / {self.receipt['support_set_total']} supporting / "
            f"{self.receipt['retained_total']} retained observations Â· page {self.page.value()}/{self.page.maximum()}")
        self.previous.setEnabled(self.page.value()>1);self.next.setEnabled(self.page.value()<self.page.maximum())


class CombinationInspector(QWidget):
    inspection_requested=Signal(object)
    sensitivity_requested=Signal(object)
    inspection_options_changed=Signal()
    report_clear_requested=Signal()
    rule_changed=Signal()

    def __init__(self,parent=None):
        super().__init__(parent);_id(self,"page")
        self._snapshot=None;self._completed=None;self._report=None;self._sensitivity=None
        self._rules=pd.DataFrame();self._extras=[];self._busy=None;self._draft_notice="";self._applying=False;self._variant_key=None
        self.pending_intent_kind="refinement_inspection"
        root=QVBoxLayout(self);self.context=_label(self,"context","Pin combinations and select a completed checkpoint.");root.addWidget(self.context)
        self.notice=_label(self,"notice");root.addWidget(self.notice)
        self.rule_selector=_combo(self,"rule");root.addWidget(self.rule_selector)
        self.inspect_button=_id(QPushButton("Inspect selected combination",self),"inspect",True);root.addWidget(self.inspect_button)
        self.views=_id(QTabWidget(self),"views");self.views.setUsesScrollButtons(True)
        self.views.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Expanding);root.addWidget(self.views)
        self.pages={};self.layouts={};self.tables={}
        for title in ("Overview","Examples and evidence","Distributions","Families and time","Simpler and centers","Filter effects","Sensitivity"):
            page=QWidget(self);layout=QVBoxLayout(page);self.views.addTab(page,title);self.pages[title]=page;self.layouts[title]=layout
        self.rule_kind=_combo(self,"rule_kind",[("All retained rules",None),("Combinations","combination"),("Single baselines","single baseline")])
        self.rule_column=_combo(self,"rule_column",[("Any column",None)])
        self.rule_support=_combo(self,"rule_support",[("Any support",None),("Original supported","original"),("Current supported","current"),("Current unsupported","unsupported")])
        self.rule_range_field=_combo(self,"rule_range_field",[(v,v) for v in ("term_count","matched","comparison_matched","exact_matched","added_by_tolerance","difference_pp")])
        self.rule_min=_id(QLineEdit(self),"rule_min");self.rule_min.setPlaceholderText("View minimum (optional)")
        self.rule_max=_id(QLineEdit(self),"rule_max");self.rule_max.setPlaceholderText("View maximum (optional)")
        self.rule_sort=_combo(self,"rule_sort",[("Original pinned order",None),("View: matches descending","matched"),("View: difference descending","difference_pp")])
        self.rule_status=_label(self,"rule_status")
        for widget in (self.rule_kind,self.rule_column,self.rule_support,self.rule_range_field,self.rule_min,self.rule_max,self.rule_sort,self.rule_status):self.layouts["Overview"].addWidget(widget)
        for name,page in (("rules","Overview"),("counts","Overview"),("comparison","Overview"),("retention","Overview"),
                ("distributions","Distributions"),("families","Families and time"),("time_blocks","Families and time"),
                ("simpler","Simpler and centers"),("centers","Simpler and centers"),("filter_effects","Filter effects"),
                ("changes_parent","Filter effects"),("changes_source","Filter effects"),("plan","Sensitivity"),("variant_patterns","Sensitivity")):
            table=StudyTable("post_refinement.inspector."+name,self);table.model.page_size=50
            table.layout().itemAt(1).layout().removeWidget(table.info);table.layout().addWidget(table.info)
            self.tables[name]=table;self.layouts[page].addWidget(_label(self,name+".caption",name.replace("_"," ").title()))
            self.layouts[page].addWidget(table)
            table.selected.connect(lambda row,name=name:self._support_selected(name,row))
            table.table.clicked.connect(lambda index,name=name:self._cell_clicked(name,index))
        self.side=_combo(self,"side",[("Current","current"),("Source","source"),("Actual parent","parent")])
        self.period=_combo(self,"period",[("Eligible combined","eligible_combined"),("Discovery","discovery"),("Later","later"),("Chronology excluded (diagnostic)","excluded")])
        self.cohort=_combo(self,"cohort",[("Both cohorts",None),("Target","target"),("Comparison","comparison"),("Cohort excluded","excluded")])
        self.match_class=_combo(self,"match",[(v.replace("_"," "),v) for v in ("all","assessable","unassessable","matched","nonmatched","exact","tolerance")])
        self.family=_combo(self,"family",[("All families",None)])
        self.block=_combo(self,"block",[("All fixed blocks",None),*[(str(i+1),i) for i in range(4)]])
        self.ready=_id(QCheckBox("Ready and timing-supported observations only",self),"ready")
        self.link_choices=_combo(self,"support_link");self.open_link=_id(QPushButton("Open exact supporting rows",self),"open_support",True)
        for widget in (self.side,self.period,self.cohort,self.match_class,self.family,self.block,self.ready,self.link_choices,self.open_link):
            self.layouts["Examples and evidence"].addWidget(widget)
        self.ledger=_LinkedLedger(self);self.layouts["Examples and evidence"].addWidget(self.ledger)
        self.details=_id(QPlainTextEdit(self),"record");self.details.setReadOnly(True);self.details.setMaximumHeight(240)
        self.layouts["Examples and evidence"].addWidget(self.details)
        self.metric_note=_label(self,"metric_note","Active common/outcome measurements are supplied by the completed checkpoint.\nInspection only: extra measurements do not change cohorts.")
        self.layouts["Distributions"].insertWidget(0,self.metric_note)
        self.metric_selector=_MetricSelector(self);self.layouts["Distributions"].addWidget(self.metric_selector)
        self.extra_list=_id(QListWidget(self),"extra_metrics");self.extra_list.setMaximumHeight(130)
        self.add_metric=_id(QPushButton("Add inspection-only metric (maximum eight)",self),"add_metric",True)
        self.remove_metric=_id(QPushButton("Remove selected inspection-only metric",self),"remove_metric",True)
        for widget in (self.add_metric,self.extra_list,self.remove_metric):self.layouts["Distributions"].addWidget(widget)
        self.omissions=_id(QListWidget(self),"omissions");self.omissions.setMaximumHeight(220)
        self.omission_status=_label(self,"omission_status")
        self.compare_button=_id(QPushButton("Compare selected omissions (no re-mining)",self),"sensitivity",True)
        self.variant_selector=_combo(self,"variant");self.inspect_variant=_id(QPushButton("Inspect variant",self),"inspect_variant",True)
        for widget in (self.omission_status,self.omissions,self.compare_button,self.variant_selector,self.inspect_variant):self.layouts["Sensitivity"].insertWidget(0,widget)
        self.clear_reports=_id(QPushButton("Clear report cache",self),"clear_reports",True);root.addWidget(self.clear_reports)
        root.addWidget(_label(self,"limitations","Retrospective full-history labels; adaptive refinement and overlapping events. No predictive-accuracy or causal-importance claim. In-session reports only."))
        self.inspect_button.clicked.connect(self.request_inspection)
        self.inspect_variant.clicked.connect(lambda:self.request_inspection(variant_key=self.variant_selector.currentData()))
        self.compare_button.clicked.connect(self.request_sensitivity);self.clear_reports.clicked.connect(self.report_clear_requested)
        self.rule_selector.currentIndexChanged.connect(self._rule_changed)
        self.metric_selector.changed.connect(lambda:self._options_changed("refinement_inspection"))
        self.add_metric.clicked.connect(self._add_metric);self.remove_metric.clicked.connect(self._remove_metric)
        self.omissions.itemChanged.connect(self._plan);self.variant_selector.currentIndexChanged.connect(self._variant_changed)
        self.open_link.clicked.connect(self._open_support)
        self.ledger.selected.connect(self._record_selected)
        for combo in (self.side,self.period,self.cohort,self.match_class,self.family,self.block):combo.currentIndexChanged.connect(self._view_changed)
        self.ready.toggled.connect(self._view_changed)
        for combo in (self.rule_kind,self.rule_column,self.rule_support,self.rule_range_field,self.rule_sort):combo.currentIndexChanged.connect(self._filter_rules)
        for edit in (self.rule_min,self.rule_max):edit.textChanged.connect(self._filter_rules)
        self.clear()

    def clear(self):
        self._snapshot=None;self._completed=None;self._report=None;self._sensitivity=None;self._extras=[];self._rules=pd.DataFrame()
        self._applying=True
        try:
            self.rule_selector.clear();self.omissions.clear();self.extra_list.clear();self.variant_selector.clear()
            for table in self.tables.values():table.set_frame(pd.DataFrame())
            self.ledger.report=None;self.ledger.set_frame(pd.DataFrame());self.details.clear()
            self.context.setText("Pin combinations and select a completed checkpoint.")
        finally:self._applying=False
        self._sync()

    def bind(self,snapshot,result):
        self._applying=True
        try:
            old_set=None if self._snapshot is None else self._snapshot["set_id"]
            self._snapshot=deepcopy(snapshot);self._completed=result.granular_definition or result.request.refinement
            self._rules=result.frame("patterns").set_index("pattern_id",drop=False).loc[list(snapshot["pinned_ids"])].reset_index(drop=True)
            if old_set!=snapshot["set_id"]:self._extras=[];self.extra_list.clear();self._report=None;self._sensitivity=None
            _choices(self.rule_column,[("Any column",None),*[(n,n) for n in snapshot["filter_context"].get("columns",{})]])
            self.metric_selector.set_context(snapshot["filter_context"])
            _choices(self.family,[("All families",None),*[(f,f) for f in snapshot["filter_context"].get("family_scope_context",{}).get("families",[])],("Ordinary controls","ordinary")])
            self.omissions.clear()
            if isinstance(self._completed,GranularRefinement):
                for purpose in ("common","outcome"):
                    for gi,group in enumerate(getattr(self._completed,purpose)):
                        for ci,p in enumerate(group.conditions):
                            omission=FilterOmission("condition",purpose,gi,ci)
                            item=QListWidgetItem(f"{omission.key}: {group.operator} {p.domain}/{p.field} {p.unit}")
                            item.setData(Qt.ItemDataRole.UserRole,omission);item.setToolTip(json.dumps(p.to_dict(),indent=2))
                            if group.enabled and p.active:item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Unchecked)
                            else:item.setText(item.text()+" (inactive)");item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEnabled)
                            self.omissions.addItem(item)
                for kind in ("anchor_range","family_scope"):
                    if getattr(self._completed,kind) is not None:
                        item=QListWidgetItem(kind+" override");item.setData(Qt.ItemDataRole.UserRole,FilterOmission(kind))
                        item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Unchecked);self.omissions.addItem(item)
            self._filter_rules()
            if self._report is not None and self._report.header["checkpoint_id"]!=snapshot["active_checkpoint_id"]:self.show_inspection(None)
            if self._sensitivity is not None and self._sensitivity.header["checkpoint_id"]!=snapshot["active_checkpoint_id"]:self.show_sensitivity(None)
        finally:self._applying=False
        self._plan();self._sync()

    def set_state(self,busy,draft_notice):
        self._busy=busy;self._draft_notice=draft_notice;self._sync()

    def _sync(self):
        present=self._snapshot is not None
        self.inspect_button.setEnabled(present and self._busy is None and self.rule_selector.currentData() is not None)
        self.compare_button.setEnabled(present and self._busy is None and isinstance(self._completed,GranularRefinement) and bool(getattr(self,"_planned",())))
        self.inspect_variant.setEnabled(present and self._busy is None and self.variant_selector.currentData() is not None)
        self.clear_reports.setEnabled(present)
        self.notice.setText(self._draft_notice+"\nReports describe the completed checkpoint and saved options, independently of the unsaved draft.")
        if present:
            text=f"Completed checkpoint {self._snapshot['active_checkpoint_id'][:16]} Â· {self._snapshot['pinned_count']} retained rules"
            if self._report is not None:
                header=self._report.header
                text+=f"\nReport {self._report.report_id[:16]} Â· rule {header['pattern_id'][:16]} Â· options {header['options_id'][:16]}"
                if header.get("variant_notice"):text+="\n"+header["variant_notice"]
                self.context.setToolTip(json.dumps(header,indent=2,default=str))
            else:
                stale=any(self._snapshot.get(k,{}).get("status")=="stale" for k in ("inspection_report","sensitivity_report"))
                text+="\nStale report cache retained and charged; explicitly inspect this checkpoint." if stale else "\nNo completed inspection shown."
            self.context.setText(text)

    def _filter_rules(self):
        if self._rules.empty:
            self.tables["rules"].set_frame(self._rules);return
        frame=self._rules.copy(deep=True)
        frame["term_count"]=[len(json.loads(v)) for v in frame.conditions]
        kind=self.rule_kind.currentData();column=self.rule_column.currentData();support=self.rule_support.currentData()
        if kind is not None:frame=frame[frame.kind==kind]
        if column is not None:frame=frame[[any(t["column"]==column for t in json.loads(v)) for v in frame.conditions]]
        if support is not None:
            field="rank_eligible" if support=="original" else "support_eligible" if "support_eligible" in frame else "rank_eligible"
            frame=frame[frame[field]==(support!="unsupported")]
        field=self.rule_range_field.currentData()
        try:
            for edit,lower in ((self.rule_min,True),(self.rule_max,False)):
                if edit.text().strip():
                    bound=float(edit.text())
                    if not math.isfinite(bound):raise ValueError("View bound must be finite")
                    frame=frame[frame[field]>=bound] if lower else frame[frame[field]<=bound]
        except ValueError as exc:
            self.rule_status.setText(str(exc));return
        order=self.rule_sort.currentData()
        if order is not None:frame=frame.sort_values(order,ascending=False,kind="stable",na_position="last")
        selected=self.rule_selector.currentData()
        self.tables["rules"].set_frame(frame)
        _choices(self.rule_selector,[(f"{r['original_order'] if 'original_order' in r else i+1}: {r['condition']}",r["pattern_id"]) for i,r in enumerate(frame.to_dict("records"))],selected)
        if selected is not None and self.rule_selector.findData(selected)<0:self.rule_selector.setCurrentIndex(-1)
        self.rule_status.setText(f"{len(frame)} visible / {len(self._rules)} retained rules. View only; original order/rank unchanged.")
        self._sync()

    def select_rule(self,pattern_id):
        index=self.rule_selector.findData(pattern_id)
        with QSignalBlocker(self.rule_selector):self.rule_selector.setCurrentIndex(index)
        self._sync()

    def _rule_changed(self):
        if not self._applying:self.rule_changed.emit()
        self._sync()

    def request_inspection(self,checked=False,*,variant_key=None):
        if self._busy is not None or self.rule_selector.currentData() is None:return
        self.inspection_requested.emit(dict(pattern_id=self.rule_selector.currentData(),options=InspectionOptions(tuple(self._extras)),variant_key=variant_key))

    def _add_metric(self):
        try:
            options=InspectionOptions((*self._extras,self.metric_selector.value()))
        except (ValueError,TypeError) as exc:self.metric_note.setText(str(exc));return
        self._extras=list(options.extra_metrics)
        self.extra_list.addItem(json.dumps(self._extras[-1].to_dict(),sort_keys=True))
        self._options_changed("refinement_inspection")

    def _remove_metric(self):
        index=self.extra_list.currentRow()
        if index>=0:self._extras.pop(index);self.extra_list.takeItem(index);self._options_changed("refinement_inspection")

    def _options_changed(self,kind):
        if self._applying:return
        self.pending_intent_kind=kind
        self.inspection_options_changed.emit()

    def _plan(self):
        self._planned=()
        if self._applying:return
        self._options_changed("refinement_sensitivity")
        if not isinstance(self._completed,GranularRefinement):
            self.omission_status.setText("Simple checkpoints are inspectable. Sensitivity requires explicit Convert/Evaluate first.");self._sync();return
        omissions=tuple(self.omissions.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.omissions.count())
            if self.omissions.item(i).checkState()==Qt.CheckState.Checked)
        if not omissions:self.omission_status.setText("Select one through eight active occurrences or explicit restrictions.");self._sync();return
        try:
            context=self._snapshot["filter_context"]
            self._planned=plan_filter_omissions(self._completed,omissions,source_request=self._snapshot["original_request"],
                column_profiles={n:c["profile_id"] for n,c in context["columns"].items()},horizon_source=context.get("horizon_source"),
                family_universe=context.get("family_scope_context",{}).get("families"))
            frame=pd.DataFrame([{k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in p.items()} for p in self._planned],dtype=object)
            self.tables["plan"].set_frame(frame)
            self.omission_status.setText(f"{len(omissions)} variants Ã— {self._snapshot['pinned_count']} complete pinned rules. "
                f"Available report budget: {134217728-self._snapshot.get('retained_total_bytes',0)} bytes. Invalid definitions are listed without execution.")
        except (ValueError,TypeError) as exc:self.omission_status.setText(str(exc))
        self._sync()

    def request_sensitivity(self):
        if self._busy is not None or not self._planned:return
        self.sensitivity_requested.emit(tuple(FilterOmission(**p["removal"]) for p in self._planned))

    def show_inspection(self,report,snapshot=None):
        if snapshot is not None:self._snapshot=deepcopy(snapshot)
        self._report=report
        if report is None:
            for name,table in self.tables.items():
                if name not in ("rules","plan","variant_patterns"):table.set_frame(pd.DataFrame())
            self.ledger.report=None;self.ledger.set_frame(pd.DataFrame());self.details.clear()
        else:
            for name,table in self.tables.items():
                if name in ("rules","plan","variant_patterns"):continue
                try:table.set_frame(report.frame(name))
                except KeyError:table.set_frame(pd.DataFrame())
            self._view_changed()
        self._sync()

    def show_sensitivity(self,report,snapshot=None):
        if snapshot is not None:self._snapshot=deepcopy(snapshot)
        self._sensitivity=report
        _choices(self.variant_selector,[] if report is None else [(key,key) for key,_ in report.evaluations])
        if report is not None:self.tables["plan"].set_frame(report.frame("plan"))
        else:self.tables["variant_patterns"].set_frame(pd.DataFrame())
        self._variant_changed();self._sync()

    def _variant_changed(self):
        if not self._applying:self._options_changed("refinement_inspection")
        if self._sensitivity is not None and self.variant_selector.currentData() is not None:
            self.tables["variant_patterns"].set_frame(self._sensitivity.frame(self.variant_selector.currentData()+"/patterns"))
        self._sync()

    def _view_changed(self):
        if self._report is None:return
        selector=dict(side=self.side.currentData(),period=self.period.currentData(),match_class=self.match_class.currentData(),ready_only=self.ready.isChecked())
        for combo,key in ((self.cohort,"cohort"),(self.family,"family"),(self.block,"block")):
            if combo.currentData() is not None:selector[key]=combo.currentData()
        try:self.ledger.load(self._report,selector)
        except ValueError as exc:self.details.setPlainText(str(exc));self.ledger.report=None;self.ledger.set_frame(pd.DataFrame())
        frame=self._report.frame("distributions")
        if not frame.empty:
            frame=frame[(frame.side==selector["side"]) & (frame.period==selector["period"]) & (frame.ready_only==selector["ready_only"])]
            for field in ("family","block"):
                frame=frame[frame[field].isna()] if field not in selector else frame[frame[field]==selector[field]]
            if "cohort" in selector:frame=frame[frame.cohort==selector["cohort"]]
            if selector["match_class"] in ("matched","nonmatched"):frame=frame[frame.matched==(selector["match_class"]=="matched")]
        self.tables["distributions"].set_frame(frame)
        self.metric_note.setText("Completed report summaries for the selected side, period, cohort, family, block and readiness. "
            "No rows means this slice has no retained observations. Active metrics keep their condition paths; extras are inspection only.")

    def _support_selected(self,name,row):
        if name=="rules" and row is not None:self.select_rule(row["pattern_id"])
        if row is None:return
        self._support_row=row
        _choices(self.link_choices,[(key.replace("_rows",""),value) for key,value in row.items() if key.endswith("_rows") and isinstance(value,str)])

    def _cell_clicked(self,name,index):
        table=self.tables[name];row=table.current_row()
        if row is None:return
        self._support_selected(name,row)
        column=table.model.frame.columns[index.column()]
        key=column if column.endswith("_rows") else column+"_rows"
        if name=="distributions":
            key={"min":"summarized_rows","q1":"summarized_rows","median":"summarized_rows","q3":"summarized_rows","max":"summarized_rows",
                "base_selected":"base_rows","values_known":"known_rows","source_coherence_unavailable":"unavailable_rows",
                "metric_timing_withheld":"timing_withheld_rows","values_summarized":"summarized_rows","available_count":"summarized_rows"}.get(column,key)
        if key in row and isinstance(row[key],str):
            self.link_choices.setCurrentIndex(self.link_choices.findData(row[key]));self._open_support()

    def _open_support(self):
        link=self.link_choices.currentData()
        if self._report is None or link is None:return
        side=self._support_row.get("side","current")
        if "reference" in self._support_row and self.link_choices.currentText()=="denominator":side=self._support_row["reference"]
        try:
            self.ledger.load(self._report,dict(side=side,link=link))
            self.views.setCurrentWidget(self.pages["Examples and evidence"])
        except ValueError as exc:self.details.setPlainText(str(exc))

    def _record_selected(self,row):
        if row is None or self._report is None:self.details.clear();return
        record=self._report.record(self.ledger.selector["side"],row["row_id"])
        self.details.setPlainText(json.dumps(record,indent=2,ensure_ascii=False))

    def refresh_display_time(self):
        for table in (*self.tables.values(),self.ledger):table.refresh_display_time()

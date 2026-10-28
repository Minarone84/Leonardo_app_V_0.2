"""Granular draft collection; calculation and source authority stay in Analysis."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDateTime, QTimeZone, QSignalBlocker, Signal, Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QCheckBox, QComboBox, QLineEdit, QLabel, QPushButton, QMessageBox, QListWidget,
    QListWidgetItem, QSizePolicy, QDateTimeEdit)

from leonardo.analysis.pattern_models import MEASUREMENT_BASES, MOVEMENT_FIELDS, DURATION_FIELDS, PULLBACK_COHORTS, _TIME_UNITS
from leonardo.analysis.refinement_models import AnchorDateRange, GranularPredicate, GranularGroup, GranularRefinement
from leonardo.analysis.pattern_refinement import validate_granular_definition
from .trend_start_results import identify


def _combo(parent, key, values):
    widget=identify(QComboBox(parent),key)
    widget.setMinimumContentsLength(8)
    widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    _choices(widget,values)
    return widget


def _choices(widget, values, selected=None):
    with QSignalBlocker(widget):
        widget.clear()
        for value in values:widget.addItem(str(value),value)
        if selected is not None and widget.findData(selected)<0:
            widget.addItem(str(selected)+' (unavailable saved choice)',selected)
        if selected is not None:widget.setCurrentIndex(widget.findData(selected))


def _label(text,parent):
    widget=QLabel(text,parent);widget.setWordWrap(True)
    widget.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
    return widget


def _number(text):
    if not text.strip():return None
    try:value=Decimal(text.strip())
    except InvalidOperation as exc:raise ValueError('Enter a finite exact number or leave the bound blank') from exc
    if not value.is_finite():raise ValueError('Bounds must be finite; NaN and infinity are unavailable values')
    return value


class _Row(QGroupBox):
    def __init__(self, group, serial, value):
        super().__init__('Condition',group)
        self.group=group;self.editor=group.editor;self.key=group.key+f'.row.{serial}';self._applying=True
        self._domain=value.domain
        root=QVBoxLayout(self);root.setContentsMargins(10,26,10,10)
        self.enabled=identify(QCheckBox('Enabled',self),self.key+'.enabled')
        top=QHBoxLayout();top.addWidget(self.enabled)
        for key,title,action in (('up','↑',lambda:group.move_row(self,-1)),('down','↓',lambda:group.move_row(self,1)),
                                 ('remove','Remove',lambda:group.remove_row(self))):
            button=identify(QPushButton(title,self),self.key+'.'+key);button.clicked.connect(action);top.addWidget(button)
        root.addLayout(top)
        form=QFormLayout();form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow);root.addLayout(form)
        self.domain=_combo(self,self.key+'.domain',('movement','duration','pullbacks','context','column','horizon'))
        self.domain.setItemText(self.domain.findData('horizon'),'Fixed-horizon price outcome')
        self.field=_combo(self,self.key+'.field',())
        self.basis=_combo(self,self.key+'.basis',MEASUREMENT_BASES)
        self.cohort=_combo(self,self.key+'.cohort',PULLBACK_COHORTS)
        self.statistic=_combo(self,self.key+'.statistic',('mean','maximum'))
        self.unit=_combo(self,self.key+'.unit',())
        self.column=_combo(self,self.key+'.column',())
        self.profile=identify(QLineEdit(self),self.key+'.profile');self.profile.setReadOnly(True)
        self.offset=_combo(self,self.key+'.offset',())
        self.horizon_bars=identify(QLineEdit(self),self.key+'.horizon_bars')
        self.horizon_bars.setText(str(value.horizon_bars if value.horizon_bars is not None else 6))
        self.horizon_reference=identify(_label('Reference: stored event close. Uses subsequent bars only. After is inspection-only.',self),self.key+'.horizon_reference')
        self.allowed=identify(QListWidget(self),self.key+'.allowed');self.allowed.setMaximumHeight(100)
        self.minimum=identify(QLineEdit(self),self.key+'.minimum');self.minimum.setPlaceholderText('No lower bound')
        self.maximum=identify(QLineEdit(self),self.key+'.maximum');self.maximum.setPlaceholderText('No upper bound')
        self.lower_inclusive=identify(QCheckBox('Include lower endpoint',self),self.key+'.lower_inclusive')
        self.upper_inclusive=identify(QCheckBox('Include upper endpoint',self),self.key+'.upper_inclusive')
        self._labels={}
        for name,title in (('domain','Domain'),('field','Measure'),('basis','Measurement basis'),('cohort','Pullback cohort'),
                ('statistic','Statistic'),('unit','Unit'),('column','Analyzed column'),('profile','Exact profile identity'),
                ('horizon_bars','Next bars (N, 1-1000)'),('horizon_reference',''),
                ('offset','Stored bar offset'),('allowed','Allowed values (empty = Any / inactive)'),('minimum','Lower bound'),
                ('lower_inclusive',''),('maximum','Upper bound'),('upper_inclusive','')):
            label=_label(title,self)
            label.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Preferred)
            self._labels[name]=label;form.addRow(label,getattr(self,name))
        self.measurement=_label('',self);identify(self.measurement,self.key+'.measurement');root.addWidget(self.measurement)
        self.enabled.setChecked(value.enabled)
        self.domain.setCurrentIndex(self.domain.findData(value.domain))
        self._configure(value.field,value.unit,value.column,value.profile_id,value.offset,value.allowed)
        for widget,selected in ((self.basis,value.basis),(self.cohort,value.cohort),(self.statistic,value.statistic)):
            if selected is not None:widget.setCurrentIndex(widget.findData(selected))
        self.minimum.setText('' if value.minimum is None else str(value.minimum))
        self.maximum.setText('' if value.maximum is None else str(value.maximum))
        self.lower_inclusive.setChecked(value.lower_inclusive);self.upper_inclusive.setChecked(value.upper_inclusive)
        self.domain.currentIndexChanged.connect(self._domain_changed)
        self.field.currentIndexChanged.connect(self._field_changed)
        self.column.currentIndexChanged.connect(self._column_changed)
        for widget in (self.basis,self.cohort,self.statistic,self.unit,self.offset):widget.currentIndexChanged.connect(self._changed)
        for widget in (self.enabled,self.lower_inclusive,self.upper_inclusive):widget.toggled.connect(self._changed)
        for widget in (self.minimum,self.maximum,self.horizon_bars):widget.textChanged.connect(self._changed)
        self.allowed.itemChanged.connect(self._changed)
        self._applying=False;self._visibility()

    def _checked(self):
        return tuple(self.allowed.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.allowed.count())
            if self.allowed.item(i).checkState()==Qt.CheckState.Checked)

    def _members(self,selected=()):
        domain,field=self.domain.currentData(),self.field.currentData()
        if domain=='context':
            values=(True,False) if field in ('up','down','range') else ('UP','DOWN','NONE') if field=='previous_direction' else self.editor._context.get('previous_families',('NONE',))
        elif domain=='column' and field=='label':
            values=self.editor._context.get('columns',{}).get(self.column.currentData(),{}).get('labels',())
        else:values=()
        values=tuple(values)
        with QSignalBlocker(self.allowed):
            self.allowed.clear()
            for value in (*values,*(v for v in selected if v not in values)):
                item=QListWidgetItem(str(value)+(' (unavailable saved choice)' if value not in values else ''))
                item.setData(Qt.ItemDataRole.UserRole,value);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if value in selected else Qt.CheckState.Unchecked)
                self.allowed.addItem(item)

    def _units(self, selected=None):
        domain,field=self.domain.currentData(),self.field.currentData()
        if domain in ('movement','horizon') or domain=='pullbacks' and field=='depth':values=('points','pct')
        elif domain=='duration' or domain=='pullbacks' and field=='recovered_duration':
            values=tuple(_TIME_UNITS) if field=='confirmation_delay' else ('bars',*_TIME_UNITS)
        elif domain=='pullbacks':values=('count',)
        elif domain=='context':values=('boolean',) if field in ('up','down','range') else ('category',)
        else:values=('native',) if field=='raw_value' else ('label',)
        _choices(self.unit,values,selected)

    def _configure(self,field=None,unit=None,column=None,profile=None,offset=None,allowed=()):
        domain=self.domain.currentData()
        fields={'movement':MOVEMENT_FIELDS,'duration':DURATION_FIELDS,'pullbacks':('count','depth','recovered_duration'),
            'context':('up','down','range','previous_direction','previous_family'),'column':('raw_value','label'),
            'horizon':('terminal_signed','terminal_directional','favorable_excursion','adverse_excursion')}
        if domain=='horizon' and field is None:field,unit='terminal_directional','pct'
        _choices(self.field,fields[domain],field);self._units(unit)
        if domain=='horizon':
            from leonardo.analysis.pattern_refinement import _gr04_required_roles
            context=self.editor._context;source=context.get('horizon_source',{})
            request=context.get('original_request');direction=request.trend_direction if request else 'UP'
            captions={'terminal_signed':'Closing price change after N bars, market-signed',
                'terminal_directional':'Closing price change after N bars, direction-adjusted',
                'favorable_excursion':'Maximum favorable candle excursion within N bars',
                'adverse_excursion':'Maximum adverse candle excursion within N bars'}
            for index in range(self.field.count()):
                name=self.field.itemData(index)
                reasons=[source.get('roles',{}).get(r,{}).get('reason','price_source_missing')
                         for r in _gr04_required_roles(name,direction)
                         if source.get('roles',{}).get(r,{}).get('status')!='available']
                item=self.field.model().item(index);item.setEnabled(not reasons)
                self.field.setItemText(index,captions[name])
                if reasons:
                    self.field.setItemText(index,captions[name]+' (unavailable: '+', '.join(reasons)+')')
                    self.field.setItemData(index,', '.join(reasons),Qt.ItemDataRole.ToolTipRole)
        columns=self.editor._context.get('columns',{})
        _choices(self.column,tuple(columns),column)
        self._profile_id = profile
        self.profile.setText('None' if profile is None else profile)
        _choices(self.offset,self.editor._context.get('offsets',()),offset)
        self._members(allowed)

    def refresh_context(self):
        self._applying=True
        try:self._configure(self.field.currentData(),self.unit.currentData(),self.column.currentData(),
            self._profile_id,self.offset.currentData(),self._checked())
        finally:self._applying=False
        self._visibility()

    def _domain_changed(self):
        if self._applying:return
        selected=self.domain.currentData()
        losing=bool(self.minimum.text().strip() or self.maximum.text().strip() or self._checked())
        if losing and QMessageBox.question(self,'Change condition domain','Changing this domain clears incompatible bounds and allowed values. Continue?',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
            with QSignalBlocker(self.domain):self.domain.setCurrentIndex(self.domain.findData(self._domain))
            return
        self._applying=True
        try:
            self._domain=selected;self.minimum.clear();self.maximum.clear();self._configure()
            self.basis.setCurrentIndex(0);self.cohort.setCurrentIndex(self.cohort.findData('internal_recovered'))
            self.statistic.setCurrentIndex(0);self.lower_inclusive.setChecked(True);self.upper_inclusive.setChecked(True)
            if selected=='horizon':self.horizon_bars.setText('6')
            if selected=='column':self._column_changed()
        finally:self._applying=False
        self._changed()

    def _field_changed(self):
        if self._applying:return
        self._applying=True
        try:self._units(self.unit.currentData());self._members(self._checked())
        finally:self._applying=False
        self._changed()

    def _column_changed(self):
        selected=self.editor._context.get('columns',{}).get(self.column.currentData(),{})
        self._profile_id = selected.get('profile_id')
        self.profile.setText(str(self._profile_id));self._members(self._checked());self._changed()

    def _visibility(self):
        domain,field=self.domain.currentData(),self.field.currentData()
        numeric=domain in ('movement','duration','pullbacks','horizon') or domain=='column' and field=='raw_value'
        show={'horizon_bars':domain=='horizon','horizon_reference':domain=='horizon',
            'basis':domain in ('movement','duration','pullbacks'),'cohort':domain=='pullbacks',
            'statistic':domain=='pullbacks' and field!='count','column':domain=='column','profile':domain=='column','offset':domain=='column',
            'allowed':not numeric or bool(self._checked()),'minimum':numeric or bool(self.minimum.text()),'maximum':numeric or bool(self.maximum.text()),
            'lower_inclusive':numeric or not self.lower_inclusive.isChecked(),'upper_inclusive':numeric or not self.upper_inclusive.isChecked()}
        for name,visible in show.items():getattr(self,name).setVisible(visible);self._labels[name].setVisible(visible)
        suffix=(f"column={self.column.currentData()} · profile={self.profile.text()} · offset={self.offset.currentData()}" if domain=='column' else
            f"basis={self.basis.currentData()}"+(f" · cohort={self.cohort.currentData()} · statistic={self.statistic.currentData()}" if domain=='pullbacks' else '') if domain!='context' else 'preceding context')
        if domain=='horizon':
            request=self.editor._context.get('original_request')
            suffix=f'N={self.horizon_bars.text()} · reference=event_close · direction={request.trend_direction if request else "unavailable"}'
        self.measurement.setText(f'{domain} / {field} / {self.unit.currentData()}\n{suffix}')

    def _changed(self,*_):
        if not self._applying:self._visibility();self.editor._changed()

    def value(self):
        domain=self.domain.currentData();field=self.field.currentData()
        selectors={}
        if domain=='horizon':
            text=self.horizon_bars.text().strip()
            digits=text.lstrip('0') or '0'
            if not text or any(c not in '0123456789' for c in text) or len(digits)>4 or not 1<=int(digits)<=1000:
                raise ValueError('Next bars N must be an unsigned integer from 1 through 1000')
            selectors['horizon_bars']=int(digits)
        if domain in ('movement','duration','pullbacks'):selectors['basis']=self.basis.currentData()
        if domain=='pullbacks':selectors.update(cohort=self.cohort.currentData(),statistic=None if field=='count' else self.statistic.currentData())
        if domain=='column':selectors.update(column=self.column.currentData(),profile_id=self._profile_id,offset=self.offset.currentData())
        return GranularPredicate(domain,field,self.unit.currentData(),**selectors,minimum=_number(self.minimum.text()),maximum=_number(self.maximum.text()),
            lower_inclusive=self.lower_inclusive.isChecked(),upper_inclusive=self.upper_inclusive.isChecked(),allowed=self._checked(),enabled=self.enabled.isChecked())


class _Group(QGroupBox):
    def __init__(self, editor, purpose, serial, value):
        super().__init__('Group',editor);self.editor=editor;self.purpose=purpose;self.key=editor._key+f'.{purpose}.group.{serial}';self.rows=[]
        root=QVBoxLayout(self);root.setContentsMargins(10,26,10,10)
        self.enabled=identify(QCheckBox('Enabled group',self),self.key+'.enabled');self.enabled.setChecked(value.enabled);root.addWidget(self.enabled)
        self.operator=_combo(self,self.key+'.operator',('ALL','ANY'));self.operator.setCurrentIndex(self.operator.findData(value.operator));root.addWidget(self.operator)
        nav=QHBoxLayout();root.addLayout(nav)
        for key,title,action in (('up','↑',lambda:editor.move_group(self,-1)),('down','↓',lambda:editor.move_group(self,1)),('remove','Remove group',lambda:editor.remove_group(self))):
            button=identify(QPushButton(title,self),self.key+'.'+key);button.clicked.connect(action);nav.addWidget(button)
        self.row_layout=QVBoxLayout();root.addLayout(self.row_layout)
        self.add=identify(QPushButton('Add condition',self),self.key+'.add_condition');root.addWidget(self.add)
        self.add.clicked.connect(lambda:self.add_row())
        for row in value.conditions:self.add_row(row,notify=False)
        self.operator.currentIndexChanged.connect(editor._changed);self.enabled.toggled.connect(editor._changed)

    def add_row(self,value=None,*,notify=True):
        if len(self.rows)>=32:return
        row=_Row(self,self.editor._serial(),value or GranularPredicate('movement','directional_move','points',basis='completed'))
        self.rows.append(row);self.row_layout.addWidget(row);self.add.setEnabled(len(self.rows)<32)
        if notify:self.editor._changed()

    def remove_row(self,row):
        self.rows.remove(row);self.row_layout.removeWidget(row);row.hide();row.deleteLater();self.add.setEnabled(True);self.editor._changed()

    def move_row(self,row,step):
        index=self.rows.index(row);target=index+step
        if 0<=target<len(self.rows):
            self.rows.insert(target,self.rows.pop(index));self.row_layout.removeWidget(row);self.row_layout.insertWidget(target,row);self.editor._changed()

    def value(self):return GranularGroup(self.operator.currentData(),tuple(r.value() for r in self.rows),self.enabled.isChecked())


class _AnchorDateRangeControls(QWidget):
    changed = Signal()

    def __init__(self, parent, *, identity_prefix):
        super().__init__(parent)
        self._applying = False
        self._request = None
        self._unavailable = {}
        self._initialized = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(_label('Common population restriction. Available in granular mode after explicit simple-filter conversion.', self))
        self.enabled = identify(QCheckBox('Limit anchor dates', self), identity_prefix+'.enabled')
        self.source = identify(_label('', self), identity_prefix+'.source')
        self.status = identify(_label('', self), identity_prefix+'.status')
        self.zone = identify(_label('', self), identity_prefix+'.zone')
        for control in (self.enabled, self.source, self.status, self.zone):
            root.addWidget(control)
        for name, caption in (('start', 'From (inclusive)'), ('end', 'Through (inclusive)')):
            root.addWidget(_label(caption, self))
            editor = identify(QDateTimeEdit(self), identity_prefix+'.'+name)
            editor.setDisplayFormat('yyyy-MM-dd HH:mm:ss.zzz')
            editor.setCalendarPopup(True)
            editor.setKeyboardTracking(False)
            setattr(self, name, editor)
            root.addWidget(editor)
            editor.dateTimeChanged.connect(lambda value, name=name: self._edited(name))
            editor.lineEdit().textEdited.connect(lambda text, name=name: self._edited(name))
            editor.lineEdit().textChanged.connect(self._refresh_tooltips)
            editor.installEventFilter(self)
            editor.lineEdit().installEventFilter(self)
        self.enabled.toggled.connect(self._edited)
        self.set_value(None)

    def _set_pair(self, start, end):
        from leonardo.gui.display_time import current_display_time_zone_name
        zone_name = current_display_time_zone_name()
        zone = QTimeZone(zone_name.encode())
        self.zone.setText('Anchor dates in '+zone_name)
        self._unavailable = {}
        for name, value in (('start', start), ('end', end)):
            editor = getattr(self, name)
            date = QDateTime.fromMSecsSinceEpoch(value, zone)
            with QSignalBlocker(editor), QSignalBlocker(editor.lineEdit()):
                editor.setTimeZone(zone)
                editor.setDateTime(date)
            if not date.isValid() or editor.dateTime().toMSecsSinceEpoch() != value:
                self._unavailable[name] = value
        self._initialized = True
        self._refresh_tooltips()

    def set_context(self, original_request_or_none):
        self._applying = True
        try:
            self._request = original_request_or_none
            if self._request is not None and (not self._initialized or not self.enabled.isChecked()):
                self._set_pair(self._request.start_ms, self._request.end_ms)
            self._refresh()
        finally:
            self._applying = False

    def set_value(self, value):
        if value is not None and type(value) is not AnchorDateRange:
            raise TypeError('Anchor date control requires AnchorDateRange or None')
        self._applying = True
        try:
            with QSignalBlocker(self.enabled):
                self.enabled.setChecked(value is not None)
            if value is not None:
                self._set_pair(value.start_ms, value.end_ms)
            elif self._request is not None:
                self._set_pair(self._request.start_ms, self._request.end_ms)
            else:
                self._set_pair(0, 0)
                self._initialized = False
            self._refresh()
        finally:
            self._applying = False

    def value(self):
        if not self.enabled.isChecked():
            return None
        if self._request is None:
            raise ValueError('Pinned anchor interval unavailable; bind the original request')
        if self._unavailable:
            raise ValueError('Anchor dates unavailable in the GUI calendar: '+str(self._unavailable)+' UTC ms')
        values = []
        for editor in (self.start, self.end):
            date = editor.dateTime()
            if not editor.hasAcceptableInput() or not date.isValid():
                raise ValueError('Enter a complete valid anchor date including milliseconds')
            value = date.toMSecsSinceEpoch()
            if QDateTime.fromMSecsSinceEpoch(value, editor.timeZone()) != date:
                raise ValueError('Anchor date cannot round-trip exact UTC milliseconds')
            values.append(value)
        return AnchorDateRange(*values)

    def _refresh(self):
        for editor in (self.start, self.end):
            editor.setEnabled(self.enabled.isChecked())
        request = self._request
        self.source.setText('Pinned outer interval unavailable' if request is None else
            f'Original pinned interval: {request.start_ms} through {request.end_ms} UTC ms, inclusive')
        if not self.enabled.isChecked():
            self.status.setText('Full original pinned interval. Date selection uses anchor timestamps only.')
            self._refresh_tooltips()
            return
        try:
            value = self.value()
            from leonardo.analysis.pattern_refinement import _grdate_resolve
            _grdate_resolve(GranularRefinement(anchor_range=value), request)
            message = f'Draft anchor interval: {value.start_ms} through {value.end_ms} UTC ms, inclusive.'
        except (ValueError, TypeError) as exc:
            message = 'Invalid date draft: '+str(exc)
        self.status.setText(message+'\nInputs and outcomes may extend outside this interval in the frozen source; the original split is unchanged.')
        self._refresh_tooltips()


    def eventFilter(self, watched, event):
        if event.type() == event.Type.ToolTip:
            self._refresh_tooltips()
        return super().eventFilter(watched, event)

    def _refresh_tooltips(self):
        enabled = self.enabled.isChecked()
        reason = ''
        try:
            self.value()
        except (ValueError, TypeError) as exc:
            reason = 'Invalid date draft: '+str(exc)
        if enabled and not reason and self.status.text().startswith('Invalid date draft:'):
            reason = self.status.text().split('\n', 1)[0]
        tips = []
        for name in ('start', 'end'):
            editor = getattr(self, name)
            if name in self._unavailable:
                tip = 'Draft unavailable in the GUI calendar: '+str(self._unavailable[name])+' UTC ms'
            elif not editor.hasAcceptableInput() or not editor.dateTime().isValid():
                tip = 'Draft unavailable: Enter a complete valid anchor date including milliseconds'
            else:
                value = editor.dateTime().toMSecsSinceEpoch()
                if enabled and not reason:
                    tip = f'Exact UTC milliseconds: {value}'
                else:
                    tip = f'Retained draft UTC milliseconds: {value}'
                    if reason:
                        tip += '\n'+reason
            if not enabled:
                tip = 'Date restriction not applied. '+tip
            editor.setToolTip(tip)
            editor.lineEdit().setToolTip(tip)
            tips.append(name+': '+tip)
        self.zone.setToolTip('\n'.join(tips))

    def _edited(self, name=None):
        if self._applying:
            return
        if isinstance(name, str):
            self._unavailable.pop(name, None)
        self._refresh()
        self.changed.emit()

    def refresh_display_time(self):
        self._applying = True
        try:
            if any(not editor.hasAcceptableInput() for editor in (self.start, self.end)):
                self._refresh()
                return
            values = [self._unavailable.get(name, getattr(self, name).dateTime().toMSecsSinceEpoch())
                      for name in ('start', 'end')]
            self._set_pair(*values)
            self._refresh()
        finally:
            self._applying = False


class GranularFilterEditor(QWidget):
    changed=Signal()

    def __init__(self,parent=None,*,identity_prefix='post_refinement.granular'):
        super().__init__(parent);self._key=identity_prefix;identify(self,identity_prefix,action=True)
        self._context={};self._next=0;self._applying=False;self.groups={'common':[],'outcome':[]};self._layouts={};self.add_buttons={}
        root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0)
        from .family_scope_controls import FamilyScopeControls
        self.family_scope=FamilyScopeControls(self,identity_prefix=identity_prefix+'.family_scope')
        root.addWidget(self.family_scope)
        self.family_scope.changed.connect(self._changed)
        self.anchor_range = _AnchorDateRangeControls(self, identity_prefix=identity_prefix+".anchor_range")
        root.addWidget(self.anchor_range)
        self.anchor_range.changed.connect(self._changed)
        root.addWidget(_label('Root operator: ALL groups. Empty common = unrestricted; empty outcome = no outcome definition. Ordinary controls use common conditions only.',self))
        self.status=_label('',self);identify(self.status,identity_prefix+'.status');root.addWidget(self.status)
        for purpose,title in (('common','Common population restrictions'),('outcome','Desired outcome')):
            section=QGroupBox(title,self);layout=QVBoxLayout(section);layout.setContentsMargins(10,26,10,10);root.addWidget(section)
            self._layouts[purpose]=QVBoxLayout();layout.addLayout(self._layouts[purpose])
            button=identify(QPushButton('Add group',section),identity_prefix+'.'+purpose+'.add_group')
            button.clicked.connect(lambda checked=False,p=purpose:self.add_group(p));layout.addWidget(button);self.add_buttons[purpose]=button
        self.set_value(GranularRefinement())

    def _serial(self):self._next+=1;return self._next

    def set_context(self,context):
        self._applying=True
        try:
            self._context=deepcopy(context)
            self.family_scope.set_context(context.get("family_scope_context",{}))
            self.anchor_range.set_context(context.get("original_request"))
            for groups in self.groups.values():
                for group in groups:
                    for row in group.rows:row.refresh_context()
        finally:self._applying=False
        self._refresh()

    def set_value(self,definition):
        if type(definition) is not GranularRefinement:raise TypeError('editor requires GranularRefinement')
        self._applying=True
        try:
            self.family_scope.set_value(definition.family_scope)
            self.anchor_range.set_value(definition.anchor_range)
            for purpose,groups in self.groups.items():
                for group in groups:self._layouts[purpose].removeWidget(group);group.hide();group.deleteLater()
                groups.clear()
                for group in getattr(definition,purpose):self.add_group(purpose,group,notify=False)
        finally:self._applying=False
        self._refresh()

    def add_group(self,purpose,value=None,*,notify=True):
        if sum(map(len,self.groups.values()))>=8:return
        group=_Group(self,purpose,self._serial(),value or GranularGroup())
        self.groups[purpose].append(group);self._layouts[purpose].addWidget(group)
        if notify:self._changed()

    def remove_group(self,group):
        self.groups[group.purpose].remove(group);self._layouts[group.purpose].removeWidget(group);group.hide();group.deleteLater();self._changed()

    def move_group(self,group,step):
        groups=self.groups[group.purpose];index=groups.index(group);target=index+step
        if 0<=target<len(groups):
            groups.insert(target,groups.pop(index));self._layouts[group.purpose].removeWidget(group);self._layouts[group.purpose].insertWidget(target,group);self._changed()

    def value(self):
        definition=GranularRefinement(**{purpose:tuple(group.value() for group in groups) for purpose,groups in self.groups.items()},
            family_scope=self.family_scope.value(), anchor_range=self.anchor_range.value())
        if not self._context:raise ValueError('Pinned editor context unavailable; repin the original discovery')
        validate_granular_definition(definition,source_request=self._context['original_request'],
            column_profiles={n:c['profile_id'] for n,c in self._context['columns'].items()},
            horizon_source=self._context.get('horizon_source'),
            family_universe=self._context.get('family_scope_context',{}).get('families'))
        return definition

    def _refresh(self):
        groups=sum(map(len,self.groups.values()));rows=sum(len(g.rows) for groups in self.groups.values() for g in groups)
        for button in self.add_buttons.values():button.setEnabled(groups<8)
        try:
            definition=self.value()
            horizons={p.horizon_bars for g in definition.common+definition.outcome if g.enabled
                      for p in g.conditions if p.active and p.domain=='horizon'}
            message=f'{definition.active_count} / 32 active occurrences · {len(horizons)} / 8 active horizons'
        except (ValueError,TypeError) as exc:message='Invalid draft: '+str(exc)
        source=self._context.get('horizon_source')
        if source:
            message+=f"\nPrice source: snapshot-only read at {source['acquired_at_ms']} UTC ms · {source['source_payload_bytes']} bytes. Retrospective snapshot prices; original historical availability is not asserted. Early chronology partitions may be excluded."
        self.status.setText(f'{groups} / 8 stored groups · {rows} stored rows (32 per group)\n'+message+"\n"+self.anchor_range.status.text())

    def refresh_display_time(self):
        self.anchor_range.refresh_display_time()

    def _changed(self,*_):
        if not self._applying:self._refresh();self.changed.emit()

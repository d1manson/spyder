# -*- coding: utf-8 -*-
#
# Copyright © 2009-2010 Pierre Raybaut
# Copyright © 2015 Daniel Manson github @d1manson
# Licensed under the terms of the MIT License
# (see spyderlib/__init__.py for details)

"""
THIS IS NOT SIMPLE!!!

There is quite a lot going on in this file.   Here's an overview of the classes:

VariableExplorer - this is the main widget/plugin which holds other things
ShellWrapper - this holds a reference to a shell and some meta data. It also has
                a method for communicationg with the shell's introspection socket.
                The on_refresh signal can be connected to listen for post-evaluation
                of user input.  See monitor.py for the available commands.    
BaseTableModel - this holds the list of props dicts for each variable and knows
                 how to map from (row, col) to individual props. 
BaseTableView - this handles the actual rendering/interactions with BaseTableModel.
                It is the widget which forms the main part of the VariableExplorer.
BaseTableViewDelegate - this does some of the work that BaseTableView can't do itself.
                specifically, it handles the custom painting of type info. The
                BaseTableView has a single instance of this class to do the needed work.
FilterWidget - This is the textbox at the bottom of the VariableExplorer. It's main 
                interaction with the VariableExplorer is via its list_changed
                Signal, and the .flist proeprty which holds the filter list.
FilterWidgetHighlighter - this subclasses QSyntaxHighlighter and is used by
                the FilterWidget.
CustomTooltip - this subclasses QDialog, making it work like a giant tooltip
VariableFilter - this holds the info that defines a single variable filter, and
                exposes a single method "match" which applies the filter, returning
                a mask of Trues/Falses.


Note that this file brings together code from three older files called:
    plugins\variableexplorer.py namespace.py and dicteditor.py
The old variableexplorer.py file now has the "_config" prefix as it only
contains code for the prefernces page.
The new version hopefully simplifies the old version of the logic and makes a bunch of
new features availble.  Of course there are likely to be a perfomance issues
and bugs introduced during the process.
"""


# pylint: disable=C0103
# pylint: disable=R0903
# pylint: disable=R0911
# pylint: disable=R0201

from __future__ import print_function
from spyderlib.qt.QtGui import (QTableView, QItemDelegate,
                                QVBoxLayout, QWidget, QColor,
                                QDialog,  QMenu,
                                QKeySequence, QLabel,
                                QToolTip, QHeaderView, QStyle,
                                QCompleter, QSplitter, QPlainTextEdit,
                                QSyntaxHighlighter, QTextCharFormat)
from spyderlib.qt.QtCore import (Qt, QModelIndex, QAbstractTableModel, Signal,
                                 Slot, QSize, QObject)
from spyderlib.qt.compat import to_qvariant
from spyderlib.widgets.externalshell.monitor import communicate


# Local import
from spyderlib.baseconfig import _
from spyderlib.guiconfig import get_font
from spyderlib.utils.qthelpers import (get_icon, add_actions, create_action)
from spyderlib.plugins.variableexplorer_config import VariableExplorerConfigPage
from spyderlib.plugins import SpyderPluginMixin
import re

class VariableFilter():
    def __init__(self, name="blank", kind='type', list_=[]):
        """ see .match method for details,  name is held for convenience."""
        self.kind = kind.lower()
        self.list_ = list_[:]
        self.name = name
    def match(self, src):
        """ src is a list of simple props dicts on which to filter.
        A mask list/tuple/generator is returned which is True for matching
        elements and false elsewhere.
        
        You can thus use this for adding selectively from one list into another,
        or simply removing values from one list.
        """
        if self.kind == 'key_exact':
            return (x['key'] in self.list_ for x in src)
        elif self.kind == 'key_regex':
            return (any(p.search(x['key']) is not None for p in self.list_) \
                    for x in src)
        elif self.kind == 'type_exact':
            return (x['type_str'] in self.list_ for x in src)
        elif self.kind == 'all':
            return (True,)*len(src)
        else:
            return []
    

# TODO: need a dialog for managing/creating filters like this and store in user prefs
DEFAULT_FILTERS = [
     VariableFilter('simples', kind='type_exact', list_=("int float"
         " complex long bool str unicode buffer int8 uint8 int16 uint16 int32"
         " uint32 int64 uint64 float16 float32 float64 complex64 complex128"
         " datetime64 timedelta64").split(" ")),
     VariableFilter('special_floats', kind='key_exact', list_=('e','euler_gamma',
          'inf','Inf', 'Infinity', 'infty', 'NaN', 'nan', 'pi')),
     VariableFilter('functions', kind='type_exact', list_=('function','ufunc', 
                    'builtin_function_or_method', 'instancemethod')),
     VariableFilter('types_etc', kind='type_exact', list_=('type','module')),
     VariableFilter('privates', kind='key_regex', list_=(re.compile('^_'),)),
     VariableFilter('caps', kind='key_regex', list_=(re.compile('^[A-Z0-9_]+$'),)),
     VariableFilter('all', kind='all'),
     VariableFilter('iterables', kind='type_exact', list_=('dict','list','set',
                                                           'tuple')),
     VariableFilter('ipython_history', kind='key_exact', list_=('In','Out')),
     VariableFilter('misc_rubbish', kind='key_exact', list_=("little_endian"
     " ScalarType sctypeDict sctypeNA sctypes typecodes typeDict typeNA"
     " using_mklfft".split(" ")))
]

def escape_for_html(s):
    return str(s).replace('&', '&amp;')\
                 .replace('<','&lt;')\
                 .replace('>','&gt;')
       

class BaseTableModel(QAbstractTableModel):
    """_data is a tuple, each item of which is a dict generated by
    get_basic_props in dictutils.  This dict contains the
    keys specified in ``column_keys`` (below) plus some other stuff.
    
    The _data corresponds to the ``key_path`` tuple, which defines how to 
    traverse from the root namespace down to a particular dict/list etc.
    
    The job of this class is to map (row, col) to information that is needed
    such as display strings, colors, tooltip info, edit mode etc.
    
    Note that although this is a "model", some of the information it offers
    is clearly more about rendering a view that raw "data" (e.g. colors).
    
    When this model needs to evaluate something, e.g. getting meta_dict,
    it does it using ``self.command('get_meta_dict', key)``. This may
    be executed locally, or it may be executed via monitor.py.  In both
    cases it is synchronous (i.e. it stalls until the answer is received).
    """
    
    # these are the keys into the properties dict corresponding to
    # columns 0,1,2,3
    columns_keys = ['key', 'type_str', 'size_str', 'value_str']
    column_header_names = {
        'key': _('name'),
        'type_str': _('type'),
        'size_str': _('size'),
        'value_str': _('value')
    }
    
    def __init__(self, parent, communicate, key_path=(), data=()):
        QAbstractTableModel.__init__(self, parent)
        self._data = data
        self.key_path = key_path or () # if key_path was None
        self.communicate = communicate
        self._valid_filters = ()
        self._flist = ()
        self.apply_filters()
        
    def set_filters(self, valid_filters, flist):
        """
        valid_filters is a list of VariableFilter instances,
        flist is a list of the form: ["-something", "-other", "+that"],
        where the names (after removing the +- prefix) correspond to
        f.name for f in valid_filters
         """
        self._valid_filters = valid_filters
        self._flist = flist
        self.apply_filters()
        
    def apply_filters(self):
        """Uses _valid_filters and _flist to filter the _data, and then 
        sorts data.
        
        We start with self._data and produce fdata. mask is the same lenght
        as self._data and is True where the element is in fdata. We need to
        know this incase we add stuff back in with "+somethign".
        """
        fdata = tuple(self._data)
        mask = [True,]*len(fdata) # True = element still in fdata
        for fstr in self._flist:
            fobj = next(f for f in self._valid_filters if f.name == fstr[1:])
            if fstr[0] == "-":
                # we need to do mask[mask==True] = ~need_to_rm ....
                need_to_rm = tuple(fobj.match(fdata))
                for sub, full in enumerate(idx for idx, msk \
                                           in enumerate(mask) if msk):
                    mask[full] = not need_to_rm[sub]                    
            elif fstr[0] == "+":
                # we need to do mask[need_to_add] = True...
                need_to_add = fobj.match(self._data)
                mask = list(msk or add for msk, add in zip(mask, need_to_add))                
            fdata = tuple(x for x, msk in zip(self._data, mask) if msk)
        self._fdata = sorted(fdata, key=lambda props: props['key'].lower())
        self.reset()
        
    def get_color_tuple(self, index, ignore_column=False):
        """Custom method used by Delegate.paint
        """
        if ignore_column or self.columns_keys[index.column()] == 'key':
            return self._fdata[index.row()]['flag_colors']
    
    def get_editor_switch(self, index, ignore_column=True):
        """Custom method used by Delegate.createEditor
        """
        if ignore_column or self.columns_keys[index.column()] == 'value':
            return self._fdata[index.row()]['editor_switch']
        
    def get_full_info(self, index):
        """Custom method used for generating tooltip text. 
        
        Although we could do basically all this work inside the get_meta_dict_foo, 
        we choose to do it here instead as it allows us a bit more control.
        """
        basic_props = self._fdata[index.row()]
        cmd = 'get_meta_dict(%s)' % str((self.key_path + (basic_props['key'],)))
        meta_props = self.communicate(cmd)
        
        value = basic_props['value_str']            
        html_str = meta_str = "" 
        if 'html' in meta_props:
            if meta_props['html'] is not None:
                html_str = '<br><br>' + meta_props['html']
            del meta_props['html']
        if 'value' in meta_props:
            value = meta_props['value'] 
            del meta_props['value']
        if value is None:
            value_str = ""
        else:
            if len(value) > 2000:
                value = value[:2000].rstrip() + "..." # QLabel strugles with long strings
            value_str = "<br><br>" + escape_for_html(value)\
                                            .replace('\n','<br>')
        
        if len(meta_props) > 0:
            meta_str = '<br><br>'\
                + ' | '.join(["<b>%s:</b>&nbsp;%s"\
                              % (escape_for_html(k), escape_for_html(v)) \
                              for k, v in meta_props.iteritems()])
                        
        return _("<h2>%s</h2><b>type:</b> %s | <b>size:</b> %s%s%s%s")\
                    % (basic_props['key'], basic_props['type_str'], basic_props['size_str'],
                       meta_str, html_str, value_str)
                    
    def columnCount(self, qindex=QModelIndex()):
        """Implement BaseClass's abstract method.
        Total number of displayable columns"""
        return len(self.columns_keys)

    def rowCount(self, qindex=QModelIndex()):
        """Implement BaseClass's abstract method.
        Total number of displayable rows"""
        return len(self._fdata)
        
    def data(self, index, role=Qt.DisplayRole):
        """Implement BaseClass's method, to provide info about a given cell."""
        if not index.isValid():
            return to_qvariant()
            
        props = self._fdata[index.row()]
        if role == Qt.DisplayRole:
            return to_qvariant(props[self.columns_keys[index.column()]])
        elif role == Qt.EditRole:
            raise NotImplementedError
        elif role == Qt.TextAlignmentRole:
            return to_qvariant(int(Qt.AlignLeft|Qt.AlignVCenter))
        elif role == Qt.FontRole:
            if self.columns_keys[index.column()] == 'value_str':
                return to_qvariant(get_font('dicteditor'))
            else:
                return to_qvariant(get_font('dicteditor_header'))
        return to_qvariant()
    
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        """Implement BaseClass's method to provide info about a given header"""
        if role == Qt.FontRole:
            return to_qvariant(get_font('dicteditor_header'))
        elif role == Qt.DisplayRole and orientation == Qt.Horizontal:
            i_column = int(section)
            return to_qvariant( 
                self.column_header_names[self.columns_keys[i_column]])
        else:
            return to_qvariant()
            
    def reset(self):
        self.beginResetModel()
        self.endResetModel()
        
        
        

class BaseTableView(QTableView):
    """This holds a BaseTableModel and makes it possible to render/interact 
    with it.  Stuff for individual cells is handled by BaseTableViewDelegate"""
    sig_option_changed = Signal(str, object)
    
    def __init__(self, parent):
        QTableView.__init__(self, parent)
        self.setItemDelegate(BaseTableViewDelegate(self))
        self.horizontalHeader().setStretchLastSection(True)
        self.custom_tooltip = None 
        self.tooltip_index = None
        self.compact_mode_column = 0
        self.compact = True
        self.only_show_column = 'key'
        self.compact_action = create_action(self, _("Compact mode"),
                                            toggled=self.toggle_compact)
        self.compact_action.setChecked(self.compact)
        self.toggle_compact(self.compact)
        menu_actions = [self.compact_action]
        self.menu = QMenu(self)
        add_actions(self.menu, menu_actions)
        
    def showRequestedColumns(self):
        model = self.model()
        if model is None:
            return
        if self.compact:
            for col_idx, col_key in enumerate(model.columns_keys):
                if col_key != self.only_show_column:
                    self.setColumnHidden(col_idx, True)
            self.horizontalHeader().setVisible(False)
        else:
            for col_idx, _ in enumerate(model.columns_keys):
                self.setColumnHidden(col_idx, False)  
            self.horizontalHeader().setVisible(True)
            
    def setModel(self, model):
        """Reimplement Qt method"""
        QTableView.setModel(self, model)
        self.showRequestedColumns()
        #self.resizeRowsToContents()  << TODO: this seems pretty slow
            
    def setup_table(self):
        """Setup table"""
        self.horizontalHeader().setStretchLastSection(True)
        self.adjust_columns()

        self.setSortingEnabled(True)
        self.sortByColumn(0, Qt.AscendingOrder)
            
    def enterEvent(self,event):
        """Reimplement Qt method"""
        if self.compact:
            self.custom_tooltip.showText("")
            self.tooltip_index = None
        QTableView.enterEvent(self,event)
        
    def leaveEvent(self,event):
        """Reimplement Qt method"""
        if self.compact:
            self.custom_tooltip.hide()
        self.tooltip_index = None
        QTableView.leaveEvent(self, event)
        
    def mouseMoveEvent(self, event):
        """Reimplement Qt method"""
        if self.compact:            
            index_over = self.indexAt(event.pos())
            if index_over.isValid() and index_over.row() != self.tooltip_index:
                self.custom_tooltip.showText(index_over.model().get_full_info(index_over))
                self.tooltip_index = index_over.row()
            QTableView.mouseMoveEvent(self, event)
        
    def mousePressEvent(self, event):
        """Reimplement Qt method"""
        if event.button() != Qt.LeftButton:
            QTableView.mousePressEvent(self, event)
            return
        index_clicked = self.indexAt(event.pos())
        if index_clicked.isValid():
            if index_clicked == self.currentIndex() \
               and index_clicked in self.selectedIndexes():
                self.clearSelection()
            else:
                QTableView.mousePressEvent(self, event)
        else:
            self.clearSelection()
            event.accept()
    
    def mouseDoubleClickEvent(self, event):
        """Reimplement Qt method"""
        index_clicked = self.indexAt(event.pos())
        if index_clicked.isValid():
            row = index_clicked.row()
            # TODO: Remove hard coded "Value" column number (3 here)
            index_clicked = index_clicked.child(row, self.only_show_column
                                                 if self.compact else 3)
            self.edit(index_clicked)
        else:
            event.accept()
    
    def keyPressEvent(self, event):
        """Reimplement Qt methods"""
        if event.key() == Qt.Key_Delete:
            self.remove_item()
        elif event.key() == Qt.Key_F2:
            self.rename_item()
        elif event == QKeySequence.Copy:
            self.copy()
        elif event == QKeySequence.Paste:
            self.paste()
        else:
            QTableView.keyPressEvent(self, event)
        
    def contextMenuEvent(self, event):
        """Reimplement Qt method"""
        # index_clicked = self.indexAt(event.pos())
        # TODO: customise menu based on index
        self.menu.popup(event.globalPos())
        event.accept()

    @Slot(bool)
    def toggle_compact(self, state):
        """Toggle compact view"""
        self.sig_option_changed.emit('compact', state)
        self.compact = state
        self.setMouseTracking(state)
        if self.custom_tooltip is None and state:
            self.custom_tooltip = CustomTooltip(self)
        self.verticalHeader().setResizeMode(
            QHeaderView.ResizeToContents if state else QHeaderView.Interactive)            
        self.showRequestedColumns()
        self.resizeColumnsToContents()
        
    @Slot()
    def edit_item(self):
        """Edit item"""
        index = self.currentIndex()
        if not index.isValid():
            return
        raise NotImplementedError

            
class BaseTableViewDelegate(QItemDelegate):
    """BaseTableView uses this class to handle the view/intereactions for
    individual cells in the table.

    Specifically, it handles the custom painting of cells, and the launching 
    of the editor and subsequent updating of values.
    """
    def __init__(self, parent=None):
        QItemDelegate.__init__(self, parent)
           
    def paint(self, painter, options, index):
        """Reimplement Qt method"""
        model = index.model()

        if options.state & QStyle.State_Selected:
            # if it's not selected then render afterwards
            QItemDelegate.paint(self, painter, options, index)
        
        color_tuple = model.get_color_tuple(index)
        if color_tuple and len(color_tuple) > 0:
            painter.save()
            rect = options.rect
            w = 4
            left = rect.right() - len(color_tuple)*w +1
            for ii, c in enumerate(color_tuple):
                painter.fillRect(left + ii*w,rect.top(),w, rect.height(),
                             QColor(c))
            painter.restore()
            
        if not (options.state & QStyle.State_Selected):
            # see above: we render before when in selected state
            QItemDelegate.paint(self, painter, options, index)
        
    def createEditor(self, parent, option, index):
        """Reimplement Qt method"""
        raise NotImplementedError 
        """               
        model = index.model()
        editor_switch = self.model.get_editor_switch(index)
        """ 
            

class CustomTooltip(QDialog):
    def __init__(self, parent):
        QDialog.__init__(self, parent)
        self.setAttribute(Qt.WA_DeleteOnClose | Qt.WA_ShowWithoutActivating)        
        vlayout = QVBoxLayout()
        self.main_text = QLabel()
        self.main_text.setWordWrap(True)        
        vlayout.addWidget(self.main_text)
        self.setLayout(vlayout)
        self.update_position()
        
        # Style the dialog to look like a tooltip (more or less)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint \
                            | Qt.WindowStaysOnTopHint) 
        self.setWindowOpacity(0.9)        
        self.setPalette(QToolTip.palette())
        self.setStyleSheet("QDialog {border: 1px solid black}")

    def update_position(self):
        left = 0
        top = 0
        parent = self.parent()
        geo = parent.geometry()
        parent_width = geo.width()
        self_width = 380        
        self_height = 300        
        self.setMinimumSize(self_width, self_height)                
        self.setMaximumSize(self_width, self_height)
        while parent:
            geo = parent.geometry()
            top += geo.top()
            left += geo.left()
            parent = parent.parent()
        window_width = geo.width()

        # Work out whether there is more space to the left or right of the parent
        right_space = window_width - (left + parent_width)    
        if right_space > left:
            left += parent_width
            self.main_text.setAlignment(Qt.AlignTop \
                                    | Qt.AlignLeft)
        else:
            left -= self_width
            self.main_text.setAlignment(Qt.AlignTop \
                                    | Qt.AlignRight)
        self.move(left, top) 

    def showText(self, text):
        # Note that we really out to hook into the move/resize events of all
        # the ancestors of this widget, but instead we just do this update here
        self.update_position()  
        self.main_text.setText(text)
        self.setVisible(len(text) > 0)
        
        

class ShellWrapper(QObject):
    """ShellWrapper holds reference to a shell (e.g. an IPython shell.)
    It knows how to send commands to the shell and get answers back.

    Connect to the on_refresh signal to get notification of refresh events
    for the shell.

    The intention is that this wrapper class should hide the details of
    what kind of shell we are dealing with. 
    
    I admit that I really don't understand the details of what is going on
    with all the threads and processes. But if it works, it works.
    """
    on_refresh = Signal()

    def __init__(self, shell, is_ipy=None):
        """shell is a shellwidget"""
        QObject.__init__(self) # we need to subclass qobject in order to use signals
        from spyderlib.widgets import internalshell
        self.shell = shell
        self.shell_id = id(shell)
        self.is_internal = isinstance(shell, internalshell.InternalShell)
        self.is_ipykernel = getattr(shell, 'is_ipykernel', False)\
                            if is_ipy is None else is_ipy
        # Hook up on_refresh to be emited when the user evaluates something in the kernel
        if not self.is_internal and not self.is_ipykernel:
            # This is the basic kernel kind            
            shell.notification_thread.refresh_namespace_browser.connect(
                                                            self.on_refresh)
        elif self.is_ipykernel and hasattr(shell, "ipyclient"):
            # this is the ipython kernel kind, although I don't fully understand it.
            shell.ipyclient.shellwidget.executed.connect(self.on_refresh.emit)

    def communicate(self, command, settings={}):
        """Sends a command to the shell and gets return value.
        See monitor.py for available commands and meanings.        
        """ 
        if not self.is_internal:
            socket = getattr(self.shell, 'introspection_socket', None)
            if socket is not None:
                return communicate(socket, command, settings)
         
class FilterWidgetHighlighter(QSyntaxHighlighter):
    def __init__(self, doc, filterWidget):
        QSyntaxHighlighter.__init__(self, doc)
        self._parentFilterWidget = filterWidget
        self.fmt_positive =  QTextCharFormat()
        self.fmt_negative =  QTextCharFormat()        
        color_ = QColor()
        color_.setNamedColor('green')
        self.fmt_positive.setForeground(color_)
        color_ = QColor()
        color_.setNamedColor('red')
        self.fmt_negative.setForeground(color_)
        
    def highlightBlock(self, text):
        p = 0
        valid = self._parentFilterWidget.valid_names 
        for w in str(text).split(" "):
            if w in valid:
                if w[0] == '+':
                    self.setFormat(p,len(w), self.fmt_positive)
                elif w[0] == '-':
                    self.setFormat(p,len(w), self.fmt_negative)
            p += len(w) + 1
            
            
class FilterWidget(QPlainTextEdit):
    """
    This is a fancy text box which lets you specify
    strings such as:
        
        -uninteresting_types -caps_only +my_special_regex
    
    The idea is that...    
    Each of the names refers to a filter in the user's list
    of filters, and the filters are applied in the order
    specified, starting with the whole list of variables,
    removing variables matching on a "-" filter, and adding
    variables matching on a "+" filter.
    
    This Widget takes care of completion, and syntax highlighting.
    The ``flist`` property holds the current list of filter names,
    including the +- prefix.  Invalid filters are not shown in this
    list.
    The list_changed signal fires when the list is updated.
    """
    list_changed = Signal()
    
    def __init__(self, parent, txt):
        QPlainTextEdit.__init__(self, parent)
        self.setToolTip(_("Show/hide variables using +-filters.\n"
                    "e.g. '-uninteresting_types -caps_only +custom_things'"))
        self.highlight = FilterWidgetHighlighter(self.document(), self)        
        self.valid_names = () # e.g. ["+thing_a", "-thing_a", "+thing_b", ...]
        self.textChanged.connect(self._update_list)
        self.flist = () # a parsed version of the text with invalid stuff missing
        self.set_completer_list(())
        self.setPlainText(txt) # TODO: this sets the text, but no highlighting or filtering occurs until you enter text manually
        self._update_list()

    def _update_list(self):
        """Called when text is change."""
        old_list = self.flist
        txt = self.toPlainText()
        self.flist = []
        for w in txt.split(" "):
            if w in self.valid_names:
                self.flist.append(w)
        if old_list != self.flist:
            self.list_changed.emit()
                    
    def sizeHint(self):
        return QSize(self.width(), 26)
            
    def set_completer_list(self, new_list=()):
        """This methods sets up the completer with a fixed
        list of filter names. It needs to be called if the
        list of filters changes, and on start up.
        """
        self.valid_names = []
        for n in new_list:
            self.valid_names += ['+' + n, '-' + n]       
        self._completer = QCompleter(self.valid_names, self)
        self._completer.activated.connect(self.insertCompletion)
        self._completer.setWidget(self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive);
    
    def cursorPosition(self):
        """QLineEdit has this method but not QPlainTextEdit"""
        return self.textCursor().position()
        
    def keyPressEvent(self, e):
        if self._completer.popup().isVisible() and\
                e.key() in (Qt.Key_Enter, 
                            Qt.Key_Return,
                            Qt.Key_Escape,
                            Qt.Key_Tab
                        ):
            e.ignore()
            return
        QPlainTextEdit.keyPressEvent(self,e)
        c = self._completer
        prefix = self.cursorWord()
        c.setCompletionPrefix(prefix)
        if len(prefix) < 1:
            c.popup().hide()
            return
        c.complete() 

    def minimumSizeHint(self):
        return QSize(0, 28)
        
    def cursorWord(self):
        """Gets the characters since the last space up to the cursor.
        """
        txt = self.toPlainText()
        cpos = self.cursorPosition()
        p = txt[:cpos].rfind(" ")
        return txt[p + 1 : cpos]

    def insertCompletion(self, completed_word):
        """The completer issues its answer to this function.
        We replace the text of the partially completed word
        with the full completed_word.
        """
        self.insertPlainText(\
            str(completed_word)[len(self._completer.completionPrefix()):])

class VariableExplorer(QWidget, SpyderPluginMixin):
    """
    Variable Explorer Plugin. It is the outermost widget. For now it simply
    holds a single BaseTableView, stored in self.editor.
    """
    CONF_SECTION = 'variable_explorer'
    CONFIGWIDGET_CLASS = VariableExplorerConfigPage
    sig_option_changed = Signal(str, object)

    def __init__(self, parent):
        QWidget.__init__(self, parent)
        SpyderPluginMixin.__init__(self, parent)
        self.initialize_plugin()
        self.editor = BaseTableView(self)
        vlayout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Vertical, self)
        vlayout.addWidget(splitter)
        splitter.addWidget(self.editor)
        txt = "-all +simples +iterables -ipython_history -caps -special_floats -privates -misc_rubbish"
        self.filter_box = FilterWidget(self, txt)
        self.filter_box.set_completer_list([f.name for f in DEFAULT_FILTERS])
        self.filter_box.list_changed.connect(self._filters_changed)
        splitter.addWidget(self.filter_box)
        splitter.setStretchFactor(0,1)
        splitter.setStretchFactor(1,0)
        self.setLayout(vlayout)
        self.id_to_shell_wrapper = {}
        self.id_current_shell = None
        self.refresh_table()
        
    def _filters_changed(self):
        """called when filter widget changes its list and when we create a 
        new model and need to apply the filters for the first time.
        """
        model = self.editor.model()
        if model is not None:
            flist = self.filter_box.flist
            model.set_filters(DEFAULT_FILTERS, flist)
        
    def refresh_table(self):
        id_ = self.id_current_shell
        if id_ is None:
            return
        comminicate_foo = self.id_to_shell_wrapper[id_].communicate 
        root_data = comminicate_foo('get_props_for_variable_explorer()')
        if root_data is not None:
            model = BaseTableModel(self.editor, comminicate_foo,
                                   None, root_data)
            self.editor.setModel(model)
            self._filters_changed() # apply filters to model

    def set_shellwidget_from_id(self, id_):
        if id_ in self.id_to_shell_wrapper and id_ != self.id_current_shell:
            self.id_current_shell = id_
            self.refresh_table()
        
    def add_shellwidget(self, shell, is_ipy=None):
        wrapped_shell = ShellWrapper(shell, is_ipy=is_ipy) 
        self.id_to_shell_wrapper[id(shell)] = wrapped_shell
        self.set_shellwidget_from_id(id(shell))
        wrapped_shell.on_refresh.connect(self.refresh_table)
             
    def remove_shellwidget(self, id_):
        if id_ in self.id_to_shell_wrapper:
            del self.id_to_shell_wrapper[id_]
            if self.id_current_shell == id_:
                self.editor.setModel(None)
                self.id_current_shell = None
    #------ SpyderPluginWidget API ---------------------------------------------
    def get_plugin_title(self):
        """Return widget title"""
        return _('Variable explorer')

    def get_plugin_icon(self):
        """Return plugin icon"""
        return get_icon('dictedit.png')
    
    def get_focus_widget(self):
        """
        Return the widget to give focus to when
        this plugin's dockwidget is raised on top-level
        """
        return self.editor
        
    def closing_plugin(self, cancelable=False):
        """Perform actions before parent main window is closed"""
        return True
        
    def refresh_plugin(self):
        """Refresh widget"""
        self.refresh_table()
    
    def get_plugin_actions(self):
        """Return a list of actions related to plugin"""
        return []
    
    def register_plugin(self):
        """Register plugin in Spyder's main window"""
        self.main.extconsole.set_variableexplorer(self)
        self.main.add_dockwidget(self)
                  


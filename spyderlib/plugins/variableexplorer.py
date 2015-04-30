# -*- coding: utf-8 -*-
#
# Copyright © 2009-2010 Pierre Raybaut
# Licensed under the terms of the MIT License
# (see spyderlib/__init__.py for details)

"""
TODO: move this into dicteditor.py

This file now only contains the config page for the variableexporer
"""

from spyderlib.qt.QtGui import (QStackedWidget, QGroupBox, QVBoxLayout, 
                                QButtonGroup, QLabel)
from spyderlib.qt.QtCore import Signal

# Local imports
from spyderlib.baseconfig import _
from spyderlib.config import CONF
from spyderlib.utils.qthelpers import get_icon
from spyderlib.utils import programs
from spyderlib.plugins import SpyderPluginMixin, PluginConfigPage


class VariableExplorerConfigPage(PluginConfigPage):
    def setup_page(self):
        ar_group = QGroupBox(_("Autorefresh"))
        ar_box = self.create_checkbox(_("Enable autorefresh"),
                                      'autorefresh')
        ar_spin = self.create_spinbox(_("Refresh interval: "),
                                      _(" ms"), 'autorefresh/timeout',
                                      min_=100, max_=1000000, step=100)
        
        filter_group = QGroupBox(_("Filter"))
        filter_data = [
            ('exclude_private', _("Exclude private references")),
            ('exclude_capitalized', _("Exclude capitalized references")),
            ('exclude_uppercase', _("Exclude all-uppercase references")),
            ('exclude_unsupported', _("Exclude unsupported data types")),
                ]
        filter_boxes = [self.create_checkbox(text, option)
                        for option, text in filter_data]

        display_group = QGroupBox(_("Display"))
        display_data = [('truncate', _("Truncate values"), '')]
        if programs.is_module_installed('numpy'):
            display_data.append(('minmax', _("Show arrays min/max"), ''))
        display_data.append(
            ('remote_editing', _("Edit data in the remote process"),
             _("Editors are opened in the remote process for NumPy "
               "arrays, PIL images, lists, tuples and dictionaries.\n"
               "This avoids transfering large amount of data between "
               "the remote process and Spyder (through the socket)."))
                            )
        display_boxes = [self.create_checkbox(text, option, tip=tip)
                         for option, text, tip in display_data]
        
        ar_layout = QVBoxLayout()
        ar_layout.addWidget(ar_box)
        ar_layout.addWidget(ar_spin)
        ar_group.setLayout(ar_layout)
        
        filter_layout = QVBoxLayout()
        for box in filter_boxes:
            filter_layout.addWidget(box)
        filter_group.setLayout(filter_layout)

        display_layout = QVBoxLayout()
        for box in display_boxes:
            display_layout.addWidget(box)
        display_group.setLayout(display_layout)


        # METADICT replacement
        makemeta_group = QGroupBox(_("make_meta_dict replacement"))
        makemeta_bg = QButtonGroup(makemeta_group)
        makemeta_label = QLabel(_("This option will override the "
                                   "default make_meta_dict function which "
                                   "defines what to display in the tooltip "
                                   "when you move the cursor over a variable "
                                   "in the variable explorer.\n"
                                   "Note changes are not reflect until after "
                                   "the application has been restarted."))
        makemeta_label.setWordWrap(True)        
        def_makemeta_radio = self.create_radiobutton(
                                        _("Default make_meta_dict function"),
                                        'makemetadict/default',
                                        button_group=makemeta_bg)
        cus_makemeta_radio = self.create_radiobutton(
                                _("Use make_meta_dict function in script:"),
                                  'makemetadict/custom',
                                  button_group=makemeta_bg)
        makemeta_file = self.create_browsefile('', 'make_meta_dict', '',
                                                filters=_("Python scripts")+\
                                                " (*.py)")
        def_makemeta_radio.toggled.connect(makemeta_file.setDisabled)
        cus_makemeta_radio.toggled.connect(makemeta_file.setEnabled)
        
        makemeta_layout = QVBoxLayout()
        makemeta_layout.addWidget(makemeta_label)
        makemeta_layout.addWidget(def_makemeta_radio)
        makemeta_layout.addWidget(cus_makemeta_radio)
        makemeta_layout.addWidget(makemeta_file)
        makemeta_group.setLayout(makemeta_layout)
        
        vlayout = QVBoxLayout()
        vlayout.addWidget(ar_group)
        vlayout.addWidget(filter_group)
        vlayout.addWidget(display_group)
        vlayout.addWidget(makemeta_group)
        vlayout.addStretch(1)
        self.setLayout(vlayout)



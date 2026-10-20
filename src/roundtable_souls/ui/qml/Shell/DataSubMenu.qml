pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQml.Models
import Theme
import Components

// A submenu: the same, one level (QML does not allow a type to contain itself).
// A menu built from a model (ui/launcher/menumodel.py): entries with their icon, shortcut hint, check mark and enabled
// flag, separators, and submenus (a row with a `sub` model). A click asks the shell to run the entry by its id. The
// model updates in place, so a menu that is open never gets rebuilt.
PopupMenu {
    id: root

    property var rows
    required property var shell

    Instantiator {
        model: root.rows

        delegate: DelegateChooser {
            role: "kind"

            DelegateChoice {
                roleValue: "separator"

                MenuSep {
                }
            }
            DelegateChoice {
                roleValue: "entry"

                MenuEntry {
                    required property var model

                    checked: model.checked
                    enabled: model.enabled
                    icon_: model.icon
                    shortcut: model.shortcut
                    text: model.label

                    onTriggered: root.shell.menuAction(model.itemId)
                }
            }
        }

        onObjectAdded: (index, object) => {
            if (object instanceof Menu)
                root.insertMenu(index, object);
            else
                root.insertItem(index, object);
        }
        onObjectRemoved: (index, object) => {
            if (object instanceof Menu)
                root.removeMenu(object);
            else
                root.removeItem(object);
        }
    }
}

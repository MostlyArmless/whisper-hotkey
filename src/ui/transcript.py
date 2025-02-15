import json
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Gdk  # noqa: E402 # type: ignore[import]


class TranscriptViewerDialog(Gtk.Dialog):
    """Dialog for viewing and copying transcripts."""

    def __init__(self, parent, transcript_path):
        super().__init__(
            title="Transcript History",
            parent=parent,
            flags=Gtk.DialogFlags.MODAL,
        )

        self.set_default_size(600, 400)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_keep_above(True)

        # Add close button
        self.add_button(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)

        # Create scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        box = self.get_content_area()
        box.pack_start(scrolled, True, True, 0)

        # Create list store and view
        self.store = Gtk.ListStore(str, str)  # timestamp, text
        self.view = Gtk.TreeView(model=self.store)

        # Add columns
        timestamp_renderer = Gtk.CellRendererText()
        timestamp_renderer.props.wrap_width = 150
        timestamp_col = Gtk.TreeViewColumn("Timestamp", timestamp_renderer, text=0)
        timestamp_col.set_resizable(True)
        timestamp_col.set_min_width(150)
        self.view.append_column(timestamp_col)

        text_renderer = Gtk.CellRendererText()
        text_renderer.props.wrap_width = 350
        text_renderer.props.wrap_mode = 2  # WRAP_WORD
        text_col = Gtk.TreeViewColumn("Transcript", text_renderer, text=1)
        text_col.set_resizable(True)
        text_col.set_min_width(350)
        self.view.append_column(text_col)

        # Replace the copy button column code with this button-styled version
        copy_renderer = Gtk.CellRendererPixbuf()
        copy_renderer.props.icon_name = "edit-copy-symbolic"
        copy_renderer.props.stock_size = Gtk.IconSize.BUTTON
        copy_renderer.props.xpad = 8
        copy_renderer.props.ypad = 6

        copy_col = Gtk.TreeViewColumn()
        copy_col.pack_start(copy_renderer, True)
        copy_col.set_fixed_width(36)
        copy_col.set_alignment(0.5)
        copy_col.set_title("")
        self.view.append_column(copy_col)

        # Update CSS styling to include button effects
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            treeview {
                padding: 5px;
            }
            treeview:hover {
                background-color: alpha(@theme_selected_bg_color, 0.1);
            }
            .cell {
                padding: 4px;
            }
            .cell:hover {
                background-color: @theme_selected_bg_color;
                border-radius: 4px;
                box-shadow: inset 0 1px rgba(255, 255, 255, 0.1),
                           inset 0 -1px rgba(0, 0, 0, 0.1);
            }
            .copy-button {
                background-color: @theme_bg_color;
                border: 1px solid @borders;
                border-radius: 4px;
                padding: 4px;
                box-shadow: inset 0 1px rgba(255, 255, 255, 0.1),
                           inset 0 -1px rgba(0, 0, 0, 0.1);
            }
            .copy-button:hover {
                background-color: @theme_selected_bg_color;
            }
        """)

        # Apply the CSS styling
        style_context = self.view.get_style_context()
        style_context.add_provider(
            css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        style_context.add_class("copy-button")

        # Update the ListStore to not include the icon name since we set it in the renderer
        self.store = Gtk.ListStore(str, str)  # timestamp, text only
        self.view.set_model(self.store)

        scrolled.add(self.view)

        # Load transcripts
        try:
            if transcript_path.exists():
                with open(transcript_path, "r", encoding="utf-8") as f:
                    transcripts = json.load(f)
                    # Sort by timestamp in reverse order (newest first)
                    for timestamp in sorted(transcripts.keys(), reverse=True):
                        self.store.append([timestamp, transcripts[timestamp]])
        except Exception as e:
            print(f"Error loading transcripts: {e}")

        # Handle click events for copy button
        self.view.connect("button-press-event", self.on_button_press)

        self.show_all()

    def on_button_press(self, treeview, event):
        """Handle click events on the tree view."""
        if event.button != 1:  # Left click only
            return False

        path_info = treeview.get_path_at_pos(int(event.x), int(event.y))
        if not path_info:
            return False

        path, column, _, _ = path_info
        if (
            column == treeview.get_columns()[-1]
        ):  # Check if it's the last column (copy button)
            model = treeview.get_model()
            text = model[path][1]  # Get transcript text

            # Copy to clipboard
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(text, -1)

            # Show a more subtle feedback tooltip instead of a dialog
            tooltip = Gtk.Window(type=Gtk.WindowType.POPUP)
            tooltip.set_type_hint(Gdk.WindowTypeHint.TOOLTIP)
            tooltip.set_position(Gtk.WindowPosition.MOUSE)

            label = Gtk.Label(label="Copied to clipboard!")
            label.set_padding(10, 5)
            tooltip.add(label)
            tooltip.show_all()

            # Remove tooltip after 1 second
            GLib.timeout_add(1000, tooltip.destroy)
            return True

        return False

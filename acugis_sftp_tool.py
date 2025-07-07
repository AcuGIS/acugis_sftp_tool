import os
import json
import paramiko
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox, QInputDialog, QProgressBar, QLineEdit, QComboBox, QDialog, QVBoxLayout, QLabel, QFormLayout, QPushButton, QHBoxLayout, QListWidget, QTreeWidget, QTreeWidgetItem, QTextEdit, QCheckBox
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt, QTimer, QCoreApplication, QEventLoop
from qgis.core import QgsProject
from qgis.utils import iface

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".sftp_uploader_config.json")

class AcugisSFTPTool:
    def __init__(self, iface):
        self.iface = iface
        self.upload_action = None
        self.config_action = None

    def initGui(self):
        plugin_dir = os.path.dirname(__file__)
        icon_path = os.path.join(plugin_dir, 'icon.png')
        config_icon_path = os.path.join(plugin_dir, 'icon_configure.png') if os.path.exists(os.path.join(plugin_dir, 'icon_configure.png')) else icon_path

        self.upload_action = QAction(QIcon(icon_path), "Upload Project Directory via SFTP", self.iface.mainWindow())
        self.upload_action.triggered.connect(self.upload_project_directory_via_sftp)
        self.iface.addToolBarIcon(self.upload_action)
        self.iface.addPluginToMenu("&AcuGIS SFTP", self.upload_action)

        self.config_action = QAction(QIcon(config_icon_path), "Configure SFTP Servers", self.iface.mainWindow())
        self.config_action.triggered.connect(self.configure_servers)
        self.iface.addToolBarIcon(self.config_action)
        self.iface.addPluginToMenu("&AcuGIS SFTP", self.config_action)
        
        # Connect to project saved signal for auto-upload
        QgsProject.instance().projectSaved.connect(self.on_project_saved)
        
    def on_project_saved(self):
        """Called when QGIS project is saved - check if auto-upload is enabled"""
        try:
            project_settings = QgsProject.instance().readEntry("AcugisSFTP", "auto_upload_settings", "")[0]
            if not project_settings:
                return
                
            settings = json.loads(project_settings)
            if not settings.get("enabled", False):
                return
                
            # Auto-upload is enabled, perform upload
            self.perform_auto_upload(settings)
            
        except Exception as e:
            print(f"Auto-upload error: {e}")

    def unload(self):
        # Disconnect project saved signal
        try:
            QgsProject.instance().projectSaved.disconnect(self.on_project_saved)
        except:
            pass
            
        self.iface.removePluginMenu("&AcuGIS SFTP", self.upload_action)
        self.iface.removeToolBarIcon(self.upload_action)
        self.iface.removePluginMenu("&AcuGIS SFTP", self.config_action)
        self.iface.removeToolBarIcon(self.config_action)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {}

    def save_config(self, config):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)

    def configure_servers(self):
        config = self.load_config()

        class ConfigDialog(QDialog):
            def __init__(self, config):
                super().__init__()
                self.setWindowTitle("Configure SFTP Servers")
                self.config = config
                self.layout = QVBoxLayout()

                logo_label = QLabel()
                logo_path = os.path.join(os.path.dirname(__file__), 'logo.png')
                if os.path.exists(logo_path):
                    logo_label.setPixmap(QIcon(logo_path).pixmap(120, 40))
                branding_label = QLabel("<b style='font-size:14pt;'>SFTP Plugin</b><br><span style='font-size:10pt;'>Secure SFTP Deployment Tool</span>")
                branding_label.setAlignment(Qt.AlignCenter)

                self.layout.addWidget(logo_label)
                self.layout.addWidget(branding_label)

                self.list_widget = QListWidget()
                self.list_widget.addItems(sorted(config.keys()))
                self.layout.addWidget(self.list_widget)

                self.form_layout = QFormLayout()
                self.server_name = QLineEdit()
                self.host = QLineEdit()
                self.username = QLineEdit()
                self.password = QLineEdit()
                self.password.setEchoMode(QLineEdit.Password)
                self.port = QLineEdit()

                self.form_layout.addRow("Server Name:", self.server_name)
                self.form_layout.addRow("Host:", self.host)
                self.form_layout.addRow("Username:", self.username)
                self.form_layout.addRow("Password:", self.password)
                self.form_layout.addRow("Port (default 3839):", self.port)
                self.layout.addLayout(self.form_layout)

                self.status_label = QLabel()
                self.status_label.setStyleSheet("color: green;")
                self.layout.addWidget(self.status_label)

                self.button_layout = QHBoxLayout()
                self.save_button = QPushButton("Save")
                self.delete_button = QPushButton("Delete")
                self.add_button = QPushButton("Add New")
                self.test_button = QPushButton("Test Connection")
                self.button_layout.addWidget(self.add_button)
                self.button_layout.addWidget(self.save_button)
                self.button_layout.addWidget(self.delete_button)
                self.button_layout.addWidget(self.test_button)

                self.layout.addLayout(self.button_layout)
                self.setLayout(self.layout)

                self.list_widget.currentItemChanged.connect(self.load_selected)
                self.save_button.clicked.connect(self.save_entry)
                self.delete_button.clicked.connect(self.delete_entry)
                self.add_button.clicked.connect(self.clear_form)
                self.test_button.clicked.connect(self.test_connection)

            def load_selected(self):
                name = self.list_widget.currentItem().text()
                entry = self.config.get(name, {})
                self.server_name.setText(name)
                self.host.setText(entry.get('host', ''))
                self.username.setText(entry.get('username', ''))
                self.password.setText(entry.get('password', ''))
                self.port.setText(str(entry.get('port', '3839')))

            def save_entry(self):
                name = self.server_name.text().strip()
                if not name:
                    self.status_label.setStyleSheet("color: red;")
                    self.status_label.setText("✖ Server name is required.")
                    QTimer.singleShot(4000, lambda: self.status_label.clear())
                    return
                self.config[name] = {
                    'host': self.host.text().strip(),
                    'username': self.username.text().strip(),
                    'password': self.password.text().strip(),
                    'port': int(self.port.text().strip()) if self.port.text().strip().isdigit() else 3839
                }
                if name not in [self.list_widget.item(i).text() for i in range(self.list_widget.count())]:
                    self.list_widget.addItem(name)
                self.status_label.setStyleSheet("color: green;")
                self.status_label.setText(f"✔ Server '{name}' saved.")
                QTimer.singleShot(4000, lambda: self.status_label.clear())

            def delete_entry(self):
                name = self.server_name.text().strip()
                if name in self.config:
                    confirm = QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete server '{name}'?", QMessageBox.Yes | QMessageBox.No)
                    if confirm != QMessageBox.Yes:
                        return
                    del self.config[name]
                    items = self.list_widget.findItems(name, Qt.MatchExactly)
                    for item in items:
                        self.list_widget.takeItem(self.list_widget.row(item))
                    self.clear_form()
                    self.status_label.setStyleSheet("color: green;")
                    self.status_label.setText(f"✔ Server '{name}' deleted.")
                    QTimer.singleShot(4000, lambda: self.status_label.clear())

            def clear_form(self):
                self.server_name.clear()
                self.host.clear()
                self.username.clear()
                self.password.clear()
                self.port.clear()

            def test_connection(self):
                self.status_label.clear()
                host = self.host.text().strip()
                username = self.username.text().strip()
                password = self.password.text().strip()
                port = int(self.port.text().strip()) if self.port.text().strip().isdigit() else 3839
                try:
                    transport = paramiko.Transport((host, port))
                    transport.connect(username=username, password=password)
                    sftp = paramiko.SFTPClient.from_transport(transport)
                    sftp.close()
                    transport.close()
                    self.status_label.setStyleSheet("color: green;")
                    self.status_label.setText("✔ Connection successful!")
                    QTimer.singleShot(4000, lambda: self.status_label.clear())
                except Exception as e:
                    self.status_label.setStyleSheet("color: red;")
                    self.status_label.setText(f"✖ Connection failed: {str(e)}")
                    QTimer.singleShot(5000, lambda: self.status_label.clear())

        dlg = ConfigDialog(config)
        dlg.exec_()
        self.save_config(config)

    def upload_project_directory_via_sftp(self):
        config = self.load_config()
        if not config:
            QMessageBox.warning(None, "No Servers Configured", "Please configure at least one SFTP server first.")
            return

        upload_dialog = QDialog()
        upload_dialog.setWindowTitle("Upload Project Directory via SFTP")
        layout = QVBoxLayout()

        logo_label = QLabel()
        logo_path = os.path.join(os.path.dirname(__file__), 'logo.png')
        if os.path.exists(logo_path):
            logo_label.setPixmap(QIcon(logo_path).pixmap(120, 40))
        branding_label = QLabel("<b style='font-size:14pt;'>SFTP Plugin</b><br><span style='font-size:10pt;'>Secure SFTP Deployment Tool</span>")
        branding_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(logo_label)
        layout.addWidget(branding_label)

        form_layout = QFormLayout()
        server_dropdown = QComboBox()
        server_names = list(config.keys())
        server_dropdown.addItems(server_names)
        remote_path_input = QLineEdit()
        ownership_input = QLineEdit("www-data:www-data")

        form_layout.addRow("Select Server:", server_dropdown)
        form_layout.addRow("Remote Path:", remote_path_input)
        form_layout.addRow("Ownership (user:group):", ownership_input)
        layout.addLayout(form_layout)

        # Add auto-upload checkbox
        auto_upload_checkbox = QCheckBox("Auto-upload changed files on project save")
        auto_upload_checkbox.setToolTip("Automatically upload project directory when QGIS project is saved")
        layout.addWidget(auto_upload_checkbox)
        
        # Load current auto-upload setting for this project
        project_settings = QgsProject.instance().readEntry("AcugisSFTP", "auto_upload_settings", "")[0]
        if project_settings:
            settings = json.loads(project_settings)
            auto_upload_checkbox.setChecked(settings.get("enabled", False))
            if settings.get("server_name"):
                index = server_dropdown.findText(settings["server_name"])
                if index >= 0:
                    server_dropdown.setCurrentIndex(index)
            if settings.get("remote_path"):
                remote_path_input.setText(settings["remote_path"])
            if settings.get("ownership"):
                ownership_input.setText(settings["ownership"])

        browse_remote_btn = QPushButton("Browse Remote Path")
        layout.addWidget(browse_remote_btn)

        button_box = QHBoxLayout()
        upload_btn = QPushButton("Upload")
        pause_btn = QPushButton("Pause")
        resume_btn = QPushButton("Resume")
        stop_btn = QPushButton("Stop")
        cancel_btn = QPushButton("Cancel")
        button_box.addWidget(upload_btn)
        button_box.addWidget(pause_btn)
        button_box.addWidget(resume_btn)
        button_box.addWidget(stop_btn)
        button_box.addWidget(cancel_btn)
        layout.addLayout(button_box)

        upload_dialog.setLayout(layout)

        def browse():
            server_name = server_dropdown.currentText()
            if not server_name:
                QMessageBox.warning(upload_dialog, "Missing Server", "Please select a server first.")
                return
            server_info = config.get(server_name, {})
            self.browse_remote_path(server_info, remote_path_input)

        browse_remote_btn.clicked.connect(browse)

        def start_upload():
            server_name = server_dropdown.currentText()
            remote_path = remote_path_input.text().strip()
            ownership_value = ownership_input.text().strip() or "www-data:www-data"
            
            # Save auto-upload settings to project
            auto_upload_settings = {
                "enabled": auto_upload_checkbox.isChecked(),
                "server_name": server_name if auto_upload_checkbox.isChecked() else "",
                "remote_path": remote_path if auto_upload_checkbox.isChecked() else "",
                "ownership": ownership_value if auto_upload_checkbox.isChecked() else ""
            }
            QgsProject.instance().writeEntry("AcugisSFTP", "auto_upload_settings", json.dumps(auto_upload_settings))
            
            if not server_name or not remote_path:
                QMessageBox.warning(upload_dialog, "Missing Info", "Please select a server and remote path.")
                return

            server_info = config[server_name]
            project_path = QgsProject.instance().fileName()
            if not project_path:
                QMessageBox.warning(None, "No Project", "Please save the QGIS project first.")
                return

            project_dir = os.path.dirname(project_path)
            try:
                transport = paramiko.Transport((server_info['host'], server_info['port']))
                transport.connect(username=server_info['username'], password=server_info['password'])
                sftp = paramiko.SFTPClient.from_transport(transport)

                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(server_info['host'], port=server_info['port'], username=server_info['username'], password=server_info['password'])

                file_list = []
                for root, _, files in os.walk(project_dir):
                    for file in files:
                        local_path = os.path.join(root, file)
                        relative_path = os.path.relpath(local_path, project_dir)
                        remote_file_path = os.path.join(remote_path, relative_path).replace("\\", "/")
                        file_list.append((local_path, remote_file_path))

                progress_bar = QProgressBar()
                progress_bar.setMinimum(0)
                progress_bar.setMaximum(len(file_list))
                progress_bar.setValue(0)
                layout.addWidget(progress_bar)

                log_output = QTextEdit()
                log_output.setReadOnly(True)
                log_output.setMinimumHeight(120)
                layout.addWidget(log_output)
                log_lines = []

                paused = False
                stopped = False

                def pause_upload():
                    nonlocal paused
                    paused = True

                def resume_upload():
                    nonlocal paused
                    paused = False

                def stop_upload():
                    nonlocal stopped
                    stopped = True

                pause_btn.clicked.connect(pause_upload)
                resume_btn.clicked.connect(resume_upload)
                stop_btn.clicked.connect(stop_upload)

                # Moved outside the loop to retain value across files
                yes_to_all = False
                for i, (local_path, remote_file_path) in enumerate(file_list):
                    if stopped:
                        break
                    while paused:
                        QCoreApplication.processEvents(QEventLoop.AllEvents, 100)
                    progress_bar.setValue(i + 1)
                    try:
                        skip_file = False
                        try:
                            remote_attr = sftp.stat(remote_file_path)
                            local_mtime = os.path.getmtime(local_path)
                            if int(local_mtime) <= int(remote_attr.st_mtime):
                                skip_file = True
                        except IOError:
                            pass

                        if skip_file and not yes_to_all:
                            overwrite = QMessageBox.question(
                                upload_dialog,
                                "File Exists",
                                f"{os.path.basename(local_path)} already exists on the server. Overwrite?",
                                QMessageBox.Yes | QMessageBox.No | QMessageBox.YesToAll | QMessageBox.NoToAll
                            )
                            if overwrite == QMessageBox.No:
                                continue
                            elif overwrite == QMessageBox.YesToAll:
                                yes_to_all = True
                            elif overwrite == QMessageBox.NoToAll:
                                break

                        remote_dir = os.path.dirname(remote_file_path)
                        dirs = remote_dir.strip('/').split('/')
                        path_so_far = ''
                        for d in dirs:
                            path_so_far = f"{path_so_far}/{d}" if path_so_far else f"/{d}"
                            try:
                                sftp.listdir(path_so_far)
                            except IOError:
                                sftp.mkdir(path_so_far)
                                ssh.exec_command(f"sudo chown {ownership_value} '{path_so_far}'")
                        sftp.put(local_path, remote_file_path)
                        ssh.exec_command(f"sudo chown {ownership_value} '{remote_file_path}'")
                        log_lines.append(f"✔ Uploaded: {os.path.basename(local_path)} → {remote_file_path}")
                        log_output.setText("\n".join(log_lines))

                    except Exception as e:
                        log_lines.append(f"✖ Failed to upload {os.path.basename(local_path)}: {e}")
                        log_output.setText("\n".join(log_lines))

                sftp.close()
                ssh.close()
                transport.close()

                QMessageBox.information(upload_dialog, "Upload Complete", "Project directory uploaded successfully.")

                if log_lines:
                    log_dialog = QDialog()
                    log_dialog.setWindowTitle("Upload Log")
                    log_layout = QVBoxLayout()
                    log_label = QLabel("<b>Upload Log:</b>")
                    log_layout.addWidget(log_label)
                    log_text = QTextEdit("\n".join(log_lines))

                    log_text.setReadOnly(True)
                    log_layout.addWidget(log_text)
                    close_btn = QPushButton("Close")
                    close_btn.clicked.connect(log_dialog.accept)
                    log_layout.addWidget(close_btn)
                    log_dialog.setLayout(log_layout)
                    log_dialog.exec_()
                upload_dialog.accept()
            except Exception as e:
                QMessageBox.critical(None, "Upload Failed", f"An error occurred: {e}")

        upload_btn.clicked.connect(start_upload)
        cancel_btn.clicked.connect(upload_dialog.reject)

        upload_dialog.exec_()

    def perform_auto_upload(self, settings):
        """Perform automatic upload in background"""
        try:
            config = self.load_config()
            server_name = settings.get("server_name")
            remote_path = settings.get("remote_path")
            ownership_value = settings.get("ownership", "www-data:www-data")
            
            if not server_name or server_name not in config:
                print(f"Auto-upload: Server '{server_name}' not found in config")
                return
                
            if not remote_path:
                print("Auto-upload: No remote path configured")
                return
                
            server_info = config[server_name]
            project_path = QgsProject.instance().fileName()
            
            if not project_path:
                print("Auto-upload: No project file found")
                return
                
            project_dir = os.path.dirname(project_path)
            
            # Show a brief notification
            self.iface.messageBar().pushMessage(
                "AcuGIS SFTP", 
                f"Checking for changes and auto-uploading to {server_name}...", 
                level=0,  # Info level
                duration=3
            )
            
            # Perform upload (simplified version without UI dialogs)
            self.upload_files_to_server(server_info, project_dir, remote_path, ownership_value)
            
            # Success notification
            self.iface.messageBar().pushMessage(
                "AcuGIS SFTP", 
                f"Auto-upload to {server_name} completed - only changed files uploaded!", 
                level=3,  # Success level
                duration=5
            )
            
        except Exception as e:
            # Error notification
            self.iface.messageBar().pushMessage(
                "AcuGIS SFTP", 
                f"Auto-upload failed: {str(e)}", 
                level=2,  # Critical level
                duration=10
            )
            print(f"Auto-upload error: {e}")

    def upload_files_to_server(self, server_info, project_dir, remote_path, ownership_value):
        """Upload files to server without UI dialogs (for auto-upload) - only changed files"""
        transport = paramiko.Transport((server_info['host'], server_info['port']))
        transport.connect(username=server_info['username'], password=server_info['password'])
        sftp = paramiko.SFTPClient.from_transport(transport)

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(server_info['host'], port=server_info['port'], 
                    username=server_info['username'], password=server_info['password'])

        try:
            # Get list of all files
            all_files = []
            for root, _, files in os.walk(project_dir):
                for file in files:
                    local_path = os.path.join(root, file)
                    relative_path = os.path.relpath(local_path, project_dir)
                    remote_file_path = os.path.join(remote_path, relative_path).replace("\\", "/")
                    all_files.append((local_path, remote_file_path))

            # Filter files that need uploading (new or changed)
            files_to_upload = []
            for local_path, remote_file_path in all_files:
                try:
                    # Get local file modification time
                    local_mtime = os.path.getmtime(local_path)
                    
                    # Check if remote file exists and get its modification time
                    try:
                        remote_attr = sftp.stat(remote_file_path)
                        remote_mtime = remote_attr.st_mtime
                        
                        # Only upload if local file is newer
                        if local_mtime > remote_mtime:
                            files_to_upload.append((local_path, remote_file_path))
                            print(f"File changed: {os.path.basename(local_path)} (local: {local_mtime}, remote: {remote_mtime})")
                        else:
                            print(f"File unchanged, skipping: {os.path.basename(local_path)}")
                            
                    except IOError:
                        # Remote file doesn't exist, upload it
                        files_to_upload.append((local_path, remote_file_path))
                        print(f"New file: {os.path.basename(local_path)}")
                        
                except Exception as e:
                    print(f"Error checking file {local_path}: {e}")
                    # If we can't check, upload it to be safe
                    files_to_upload.append((local_path, remote_file_path))

            if not files_to_upload:
                print("No files need uploading - all files are up to date")
                return

            print(f"Uploading {len(files_to_upload)} changed/new files out of {len(all_files)} total files")

            # Upload only the files that need uploading
            for local_path, remote_file_path in files_to_upload:
                try:
                    # Create remote directories if needed
                    remote_dir = os.path.dirname(remote_file_path)
                    dirs = remote_dir.strip('/').split('/')
                    path_so_far = ''
                    for d in dirs:
                        if d:  # Skip empty strings
                            path_so_far = f"{path_so_far}/{d}" if path_so_far else f"/{d}"
                            try:
                                sftp.listdir(path_so_far)
                            except IOError:
                                sftp.mkdir(path_so_far)
                                ssh.exec_command(f"sudo chown {ownership_value} '{path_so_far}'")
                    
                    # Upload file
                    sftp.put(local_path, remote_file_path)
                    ssh.exec_command(f"sudo chown {ownership_value} '{remote_file_path}'")
                    print(f"✔ Uploaded: {os.path.basename(local_path)}")
                    
                except Exception as e:
                    print(f"Failed to upload {local_path}: {e}")
                    
        finally:
            sftp.close()
            ssh.close()
            transport.close()

    def browse_remote_path(self, server_info, remote_path_input):
        try:
            transport = paramiko.Transport((server_info['host'], server_info['port']))
            transport.connect(username=server_info['username'], password=server_info['password'])
            sftp = paramiko.SFTPClient.from_transport(transport)

            browser_dialog = QDialog()
            browser_dialog.setWindowTitle("Select Remote Directory")
            browser_dialog.resize(500, 400)

            layout = QVBoxLayout()
            path_label = QLabel("Selected: /")
            layout.addWidget(path_label)

            tree = QTreeWidget()
            tree.setHeaderHidden(True)
            layout.addWidget(tree)

            folder_icon = QIcon.fromTheme("folder")
            if folder_icon.isNull():
                folder_icon = QIcon("/usr/share/icons/oxygen/16x16/places/folder.png")

            def populate(item, path):
                try:
                    entries = sftp.listdir_attr(path)
                    dirs = [e for e in entries if str(e.longname).startswith('d')]
                    for d in sorted(dirs, key=lambda x: x.filename):
                        child = QTreeWidgetItem([d.filename])
                        child.setIcon(0, folder_icon)
                        child.setData(0, Qt.UserRole, os.path.join(path, d.filename).replace("\\", "/"))
                        child.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
                        item.addChild(child)
                except Exception as e:
                    print(f"Failed to list {path}: {e}")

            root_item = QTreeWidgetItem(["/"])
            root_item.setIcon(0, folder_icon)
            root_item.setData(0, Qt.UserRole, "/")
            root_item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
            tree.addTopLevelItem(root_item)
            populate(root_item, "/")
            root_item.setExpanded(True)

            def on_item_expanded(item):
                if item.childCount() == 0:
                    path = item.data(0, Qt.UserRole)
                    populate(item, path)

            tree.itemExpanded.connect(on_item_expanded)

            def on_item_clicked(item, column):
                path = item.data(0, Qt.UserRole)
                path_label.setText(f"Selected: {path}")

            tree.itemClicked.connect(on_item_clicked)

            select_btn = QPushButton("Select This Folder")
            layout.addWidget(select_btn)

            def select_folder():
                selected_item = tree.currentItem()
                if not selected_item:
                    QMessageBox.warning(browser_dialog, "No Selection", "Please select a folder.")
                    return
                path = selected_item.data(0, Qt.UserRole)
                remote_path_input.setText(path)
                browser_dialog.accept()

            select_btn.clicked.connect(select_folder)
            browser_dialog.setLayout(layout)
            browser_dialog.exec_()

            sftp.close()
            transport.close()

        except Exception as e:
            QMessageBox.critical(None, "Connection Failed", f"Failed to connect: {e}")

def classFactory(iface):
    return AcugisSFTPTool(iface)
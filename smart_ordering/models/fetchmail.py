from odoo import fields, models


class FetchmailServer(models.Model):
    _inherit = 'fetchmail.server'

    imap_folder = fields.Char(string='IMAP Folder', default='INBOX')

    def _connect__(self, allow_archived=False):
        connection = super()._connect__(allow_archived=allow_archived)
        if self.server_type == 'imap' and self.imap_folder and self.imap_folder != 'INBOX':
            folder = self.imap_folder
            def folder_check():
                connection.select(f'"{folder}"')
                _, data = connection.search(None, '(UNSEEN)')
                connection._unread_messages = data[0].split() if data and data[0] else []
                connection._unread_messages.reverse()
                return len(connection._unread_messages)
            connection.check_unread_messages = folder_check
        return connection

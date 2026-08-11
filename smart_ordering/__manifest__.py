{
    'name': 'Smart Ordering',
    'version': '19.0.1.0.0',
    'category': 'Sales',
    'summary': 'Automated order intake from email',
    'depends': ['mail', 'sale', 'microsoft_outlook'],
    'data': [
        'security/ir.model.access.csv',
        'views/order_views.xml',
        'views/mail_account_views.xml',
        'views/outlook_account_views.xml',
        'data/settings_data.xml',
        'views/settings_views.xml',
        'data/cron.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}

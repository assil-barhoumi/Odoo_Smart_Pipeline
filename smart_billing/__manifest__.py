{
    'name': 'Smart Billing',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Automated invoice intake from email',
    'depends': ['mail', 'account'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}

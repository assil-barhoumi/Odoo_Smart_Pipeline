{
    'name': 'Smart Ordering',
    'version': '19.0.1.0.0',
    'category': 'Sales',
    'summary': 'Automated order intake from email',
    'depends': ['mail', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/order_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}

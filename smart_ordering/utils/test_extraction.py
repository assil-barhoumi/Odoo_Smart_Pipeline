# run: docker exec -it odoo19-footer python3 /mnt/extra-addons/smart_ordering/utils/test_extraction.py <groq_api_key>

import sys
sys.path.insert(0, '/mnt/extra-addons/smart_ordering/utils')

from llm_utils import extract_order

api_key = sys.argv[1] if len(sys.argv) > 1 else ''

bodies = {
    "fr_basic": "Bonjour, je suis Assil Barhoumi de la société Creacy. Je souhaite commander: 10 chaises de bureau, 3 tables de réunion, 5 armoires métalliques, 2 imprimantes laser couleur et 20 ramettes papier A4. Livraison sous 48h.",
    "ar_basic": "السلام عليكم، أنا أسيل برهومي من شركة كرياسي. أرغب في طلب: 5 طاولات مكتبية، 10 كراسي مكتب، 3 حواسيب محمولة، 2 طابعات ليزر و 50 رزمة ورق A4. شكراً.",
    "fr_ar_mixed": "Bonjour, je voudrais commander 5 طابعات ليزر et 20 رزمة ورق A4 et 3 شاشات 27 pouces. Merci.",
    "fr_no_name": "Bonjour, nous avons besoin de 15 chaises ergonomiques, 4 tables de conférence, 2 vidéoprojecteurs et 1 tableau blanc interactif. Merci de nous envoyer un devis.",
    "fr_with_noise": "Bonjour, commande urgente: 5 imprimantes HP LaserJet et 100 ramettes papier A4 et 2 cartouches toner noir. Cordialement, Sami Amor.\n\n--\nCe message a été vérifié par Avast Antivirus.\nwww.avast.com",
    "fr_ar_hard": "Bonjour, je suis Assil Barhoumi de la société Creacy. Je voudrais commander: 3 imprimantes laser couleur, عشرة كراسي مكتب, une vingtaine de ramettes papier A4, 2 écrans 27 pouces full HD, و برميل حبر أسود للطابعة Canon بدون كمية محددة. Livraison souhaitée lundi, paiement à la livraison.",
    "ambiguous": "Bonsoir, pouvez-vous m'envoyer votre catalogue de chaises et de bureaux ainsi que vos tarifs? Merci.",
}

for name, body in bodies.items():
    print(f"\n--- {name} ---")
    print(f"input: {body}")
    print(f"output: {extract_order(body, api_key)}")

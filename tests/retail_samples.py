"""Order emails modelled on what Walmart, Target and Best Buy send (table-based HTML, hidden preheader padding, text parts full of
tracking links), with the answer the parser should give for each. Used by selftest.py."""
from email.message import EmailMessage
from email.utils import formatdate

PAD = "&zwnj;&nbsp;" * 60 + "&#847;" * 20


def _html(pre, rows):
    cells = "".join(f'<tr><td style="padding:8px 0;font-family:Arial">{r}</td></tr>' for r in rows)
    return (f'<!doctype html><html><head><style>.x{{color:red}}</style></head><body>'
            f'<div style="display:none;max-height:0;overflow:hidden">{pre}{PAD}</div>'
            f'<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center"><img src="https://img.example/logo.png" alt=""></td></tr>'
            f'<tr><td><table width="600">{cells}</table></td></tr>'
            f'<tr><td style="font-size:11px">Help | Returns | Privacy | © 2026</td></tr></table></body></html>')


def _item(name, qty, price, extra=""):
    return (f'<table><tr><td><img src="https://img.example/p.jpg" width="80"></td><td><a href="https://click.example/?q=1">{name}</a>{extra}'
            f'<br><span>Qty: {qty}</span></td><td align="right">${price}</td></tr></table>')


def _msg(frm, subject, html, when):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Date"] = frm, "honker.wintry-0n@icloud.com", subject, formatdate(when)
    m["Message-ID"] = f"<{abs(hash((frm, subject, when)))}@retail.test>"
    junk = "\n".join(f"https://click.example.com/?qs={i:064x} " for i in range(30))
    m.set_content(f"{subject}\n\n&zwnj; &zwnj; &zwnj; &zwnj; &zwnj; &zwnj; &zwnj;\n{junk}\n")
    m.add_alternative(html, subtype="html")
    return m


T0 = 1794000000  # Nov 2026

WALMART = "Walmart.com <help@walmart.com>"
TARGET = "Target <orders@oe.target.com>"
BESTBUY = "Best Buy <BestBuyInfo@emailinfo.bestbuy.com>"

SAMPLES = [
    # ---------------- Walmart
    (_msg(WALMART, "Thanks for your order", _html("We got your order! Here are the details.", [
        "<h1>Thanks for your order, Tim</h1>", "Order date: Nov 14, 2026", "Order# 2000140-27154038",
        "<b>Arrives by Wed, Nov 18</b>",
        _item("Pokémon Scarlet &amp; Violet Prismatic Evolutions Elite Trainer Box", 2, "99.94"),
        _item("Pokémon TCG Surging Sparks Booster Bundle", 1, "26.94"),
        "Subtotal $126.88", "Shipping Free", "Tax $9.52", "<b>Total $136.40</b>", "Payment method: Visa ending in 4242"]), T0),
     {"retailer": "Walmart", "order_number": "2000140-27154038", "status": "placed", "total": 136.40, "items": 2}),
    (_msg(WALMART, "Shipped: Pokémon Scarlet & Violet Prismatic Evolutions Elite...", _html("Your package is on the way.", [
        "<h1>Your package shipped!</h1>", "Order# 2000140-27154038", "Arrives by Wed, Nov 18",
        "Tracking number: 1Z999AA10123456784", _item("Pokémon Scarlet &amp; Violet Prismatic Evolutions Elite Trainer Box", 2, "99.94")]), T0 + 86400),
     {"retailer": "Walmart", "order_number": "2000140-27154038", "status": "shipped", "tracking": "1Z999AA10123456784"}),
    (_msg(WALMART, "Arriving today: your Walmart order", _html("Your delivery is almost here", [
        "Your package is out for delivery", "Order# 2000140-27154038"]), T0 + 2 * 86400),
     {"retailer": "Walmart", "order_number": "2000140-27154038", "status": "out_for_delivery"}),
    (_msg(WALMART, "Delivered: Pokémon Scarlet & Violet Prismatic Evolutions Elite...", _html("Your package was delivered.", [
        "<h1>Your package was delivered</h1>", "Order# 2000140-27154038", "Delivered Nov 18, front door"]), T0 + 3 * 86400),
     {"retailer": "Walmart", "order_number": "2000140-27154038", "status": "delivered"}),
    (_msg(WALMART, "Your order was canceled", _html("We're sorry", [
        "We canceled your order", "Order number 2000141-11223344", "If you were charged, your refund will be issued to your original payment method."]), T0),
     {"retailer": "Walmart", "order_number": "2000141-11223344", "status": "cancelled"}),
    (_msg(WALMART, "An item in your order was canceled", _html("Item canceled", [
        "One item in your order was canceled", "Order# 2000142-55667788", _item("Pokémon TCG Surging Sparks Booster Bundle", 1, "26.94")]), T0),
     {"retailer": "Walmart", "order_number": "2000142-55667788", "status": "partially_cancelled"}),
    # ---------------- Target
    (_msg(TARGET, "Thanks for shopping with us! Here's your order #: 102003492819473.", _html("Thanks for shopping with us!", [
        "<h1>Thanks for your order!</h1>", "We'll let you know when it ships.", "Order #102003492819473", "Placed November 14, 2026",
        _item("Pokémon Trading Card Game: Scarlet &amp; Violet—Prismatic Evolutions Booster Bundle", 2, "53.98", "<br>DPCI: 087-35-0221"),
        "Subtotal $53.98", "Estimated tax $4.32", "Shipping Free", "Total $58.30", "Visa *4242"]), T0),
     {"retailer": "Target", "order_number": "102003492819473", "status": "placed", "total": 58.30, "items": 1, "qty": 2}),
    (_msg(TARGET, "Your order is on the way!", _html("Heads up! Your package is on the way.", [
        "<h1>Your order is on the way</h1>", "Order #102003492819473", "Tracking # 9400111899223817265841", "Carrier: USPS"]), T0 + 86400),
     {"retailer": "Target", "order_number": "102003492819473", "status": "shipped", "tracking": "9400111899223817265841"}),
    (_msg(TARGET, "Your order was delivered", _html("Your package arrived.", ["Your package was delivered", "Order #102003492819473"]), T0 + 3 * 86400),
     {"retailer": "Target", "order_number": "102003492819473", "status": "delivered"}),
    (_msg(TARGET, "We had to cancel some items from your order", _html("Sorry about that", [
        "We had to cancel some items", "Order #102003492819474", _item("Pokémon TCG: Mega Evolution Elite Trainer Box", 1, "49.99")]), T0),
     {"retailer": "Target", "order_number": "102003492819474", "status": "partially_cancelled"}),
    (_msg(TARGET, "Your order has been canceled", _html("Order canceled", ["Your order has been canceled", "Order #102003492819475"]), T0),
     {"retailer": "Target", "order_number": "102003492819475", "status": "cancelled"}),
    (_msg(TARGET, "Your order is ready for pickup", _html("Come on in", ["Your order is ready", "Order #102003492819476", "Pick up at Target Ann Arbor"]), T0),
     {"retailer": "Target", "order_number": "102003492819476", "status": "delivered"}),
    # ---------------- Best Buy
    (_msg(BESTBUY, "Thanks for your order", _html("We've received your order.", [
        "<h1>Thanks for your order, Tim.</h1>", "Order Number: BBY01-806123456789", "Order Date: Nov 14, 2026",
        _item("Pokémon - Trading Card Game: Scarlet &amp; Violet Prismatic Evolutions Super Premium Collection", 1, "119.99", "<br>SKU: 6606082"),
        "Subtotal: $119.99", "Shipping: FREE", "Estimated Sales Tax: $9.60", "Total: $129.59"]), T0),
     {"retailer": "Best Buy", "order_number": "BBY01-806123456789", "status": "placed", "total": 129.59, "items": 1}),
    (_msg(BESTBUY, "Your order has shipped", _html("Your items are on their way.", [
        "Your order has shipped", "Order #BBY01-806123456789", "Tracking Number: 1Z0A1B2C3456789012", "UPS"]), T0 + 86400),
     {"retailer": "Best Buy", "order_number": "BBY01-806123456789", "status": "shipped", "tracking": "1Z0A1B2C3456789012"}),
    (_msg(BESTBUY, "Your order is ready for pickup", _html("Come get it.", ["Your order is ready for store pickup", "Order Number: BBY01-806123456790"]), T0),
     {"retailer": "Best Buy", "order_number": "BBY01-806123456790", "status": "delivered"}),
    (_msg(BESTBUY, "Your order has been canceled", _html("Order canceled", ["We've canceled your order.", "Order Number: BBY01-806123456791"]), T0),
     {"retailer": "Best Buy", "order_number": "BBY01-806123456791", "status": "cancelled"}),
    (_msg(BESTBUY, "Your package has been delivered", _html("Delivered", ["Your package was delivered", "Order #BBY01-806123456789"]), T0 + 3 * 86400),
     {"retailer": "Best Buy", "order_number": "BBY01-806123456789", "status": "delivered"}),
]

# The same emails as they arrive at an iCloud Hide My Email address: Apple rewrites the sender so replies go through the relay.
RELAYED = [
    (_msg("Target <orders_at_oe_target_com_x7k2qzpd@icloud.com>", "Thanks for shopping with us! Here's your order #: 102003492819480.", _html("Thanks for shopping with us!", [
        "<h1>Thanks for your order!</h1>", "Order #102003492819480", _item("Pokémon TCG: Mega Evolution Booster Bundle", 1, "29.99"), "Subtotal $29.99", "Total $32.39"]), T0),
     {"retailer": "Target", "order_number": "102003492819480", "status": "placed", "total": 32.39}),
    (_msg("Target <orders_at_oe_target_com_x7k2qzpd@icloud.com>", "Your order is on the way!", _html("On the way", ["Your package is on the way", "Order #102003492819480"]), T0 + 86400),
     {"retailer": "Target", "order_number": "102003492819480", "status": "shipped"}),
    (_msg('"Walmart.com" <help_at_walmart_com_ab12cd34@icloud.com>', "Delivered: Pokémon TCG Booster Bundle", _html("Delivered", ["Your package was delivered", "Order# 2000150-12345678"]), T0),
     {"retailer": "Walmart", "order_number": "2000150-12345678", "status": "delivered"}),
    (_msg("Best Buy <BestBuyInfo_at_emailinfo_bestbuy_com_9zz1q8@icloud.com>", "Your order has shipped", _html("Shipped", ["Your order has shipped", "Order #BBY01-806123456799"]), T0),
     {"retailer": "Best Buy", "order_number": "BBY01-806123456799", "status": "shipped"}),
]
SAMPLES = SAMPLES + RELAYED

# Marketing mail from the same retailers must not become orders or land in Needs attention.
NEGATIVE = [
    _msg("Target <targetnews@em.target.com>", "Free shipping on your next order 🎉", _html("Deals!", ["Shop deals", "Order online, pick up today"]), T0),
    _msg("Best Buy <BestBuy@email.bestbuy.com>", "Order now: deals end tonight", _html("Deals", ["Top deals", "Shop now"]), T0),
    _msg("Target <targetnews_at_em_target_com_q9w8e7@icloud.com>", "Free shipping on your next order", _html("Deals!", ["Shop deals"]), T0),
]

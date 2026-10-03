"""Demo data: shops around Koramangala 5th Block (Bengaluru), a product catalogue with
multilingual aliases, per-shop inventory and two weeks of synthetic demand history.

All names, UPI IDs and numbers here are made up for the prototype.
"""

SHOPS = [
    # id, name, owner, lat, lng, upi
    (1, "Sri Lakshmi Stores", "Ramesh", 12.93520, 77.62450, "srilakshmi.demo@upi"),
    (2, "Sharma General Store", "Vikas Sharma", 12.93650, 77.62600, "sharmags.demo@upi"),
    (3, "Annapoorna Provisions", "Kavya", 12.93400, 77.62300, "annapoorna.demo@upi"),
    (4, "Fresh Mart Daily", "Imran", 12.93720, 77.62280, "freshmart.demo@upi"),
    (5, "Basaveshwara Kirana", "Manjunath", 12.93300, 77.62620, "basaveshwara.demo@upi"),
    (6, "Green Leaf Organics", "Priya", 12.93950, 77.62700, "greenleaf.demo@upi"),
]

# id, name, price (approx. ₹), category, aliases (English / Hinglish / Hindi / Kannada / Kanglish)
PRODUCTS = [
    (1, "Amul Taaza Milk 1L", 54, "Dairy", ["amul taaza", "taaza", "amul milk", "milk", "doodh", "dudh", "दूध", "अमूल दूध", "haalu", "ಹಾಲು", "ಅಮುಲ್"]),
    (2, "Oat Milk 1L", 210, "Dairy", ["oat milk", "oats milk", "oats wala doodh", "oat doodh", "oats doodh", "ओट मिल्क", "ओट्स दूध", "ओट्स मिल्क", "ಓಟ್ ಮಿಲ್ಕ್", "ಓಟ್ಸ್ ಹಾಲು"]),
    (3, "Greek Yogurt 400g", 120, "Dairy", ["greek yogurt", "greek yoghurt", "greek curd", "greek dahi", "ग्रीक योगर्ट", "ग्रीक दही", "ಗ್ರೀಕ್ ಮೊಸರು", "ಗ್ರೀಕ್ ಯೋಗರ್ಟ್"]),
    (4, "Curd 400g", 35, "Dairy", ["curd", "dahi", "दही", "mosaru", "ಮೊಸರು", "thayir"]),
    (5, "Paneer 200g", 90, "Dairy", ["paneer", "पनीर", "ಪನೀರ್", "cottage cheese"]),
    (6, "Amul Butter 100g", 58, "Dairy", ["butter", "amul butter", "makhan", "मक्खन", "बटर", "benne", "ಬೆಣ್ಣೆ"]),
    (7, "White Bread 400g", 45, "Bakery", ["bread", "white bread", "double roti", "ब्रेड", "ಬ್ರೆಡ್"]),
    (8, "Brown Bread 400g", 55, "Bakery", ["brown bread", "atta bread", "ब्राउन ब्रेड", "ಬ್ರೌನ್ ಬ್ರೆಡ್"]),
    (9, "Eggs (6 pack)", 48, "Dairy", ["eggs", "egg", "anda", "ande", "अंडे", "अंडा", "motte", "ಮೊಟ್ಟೆ"]),
    (10, "Maggi Masala Noodles 70g", 14, "Snacks", ["maggi", "maggie", "maggi noodles", "noodles", "मैगी", "ಮ್ಯಾಗಿ"]),
    (11, "Maggi Masala-ae-Magic Sachet", 5, "Spices", ["maggi masala", "masala sachet", "maggi masala sachet", "masala ae magic", "मैगी मसाला", "ಮ್ಯಾಗಿ ಮಸಾಲ"]),
    (12, "Tata Salt 1kg", 28, "Staples", ["salt", "namak", "नमक", "uppu", "ಉಪ್ಪು", "tata salt"]),
    (13, "Sugar 1kg", 48, "Staples", ["sugar", "cheeni", "chini", "चीनी", "shakkar", "sakkare", "ಸಕ್ಕರೆ"]),
    (14, "Aashirvaad Atta 5kg", 260, "Staples", ["atta", "aata", "आटा", "wheat flour", "godhi hittu", "ಗೋಧಿ ಹಿಟ್ಟು", "aashirvaad"]),
    (15, "Sona Masoori Rice 5kg", 350, "Staples", ["rice", "chawal", "चावल", "akki", "ಅಕ್ಕಿ", "sona masoori"]),
    (16, "Toor Dal 1kg", 160, "Staples", ["toor dal", "tur dal", "arhar dal", "dal", "daal", "दाल", "togari bele", "ತೊಗರಿ ಬೇಳೆ"]),
    (17, "Sunflower Oil 1L", 150, "Staples", ["sunflower oil", "oil", "tel", "तेल", "enne", "ಎಣ್ಣೆ", "fortune oil"]),
    (18, "Tata Tea Gold 250g", 150, "Beverages", ["tea", "chai", "chai patti", "चाय", "चाय पत्ती", "ಟೀ", "tata tea"]),
    (19, "Nescafe Classic 50g", 175, "Beverages", ["nescafe", "instant coffee", "coffee", "कॉफी", "ಕಾಫಿ"]),
    (20, "Filter Coffee Powder 200g", 120, "Beverages", ["filter coffee", "coffee powder", "kaapi pudi", "ಕಾಫಿ ಪುಡಿ"]),
    (21, "Parle-G 250g", 25, "Snacks", ["parle g", "parle", "biscuit", "biscuits", "बिस्कुट", "ಬಿಸ್ಕತ್"]),
    (22, "Lay's Classic 50g", 20, "Snacks", ["lays", "chips", "चिप्स", "ಚಿಪ್ಸ್"]),
    (23, "Coca-Cola 750ml", 45, "Beverages", ["coke", "coca cola", "cola", "cold drink", "कोक", "ಕೋಕ್"]),
    (24, "Bisleri Water 1L", 20, "Beverages", ["water", "water bottle", "bisleri", "paani", "पानी", "neeru", "ನೀರು"]),
    (25, "Dettol Handwash Refill 750ml", 99, "Home care", ["dettol refill", "handwash refill", "dettol", "handwash", "डेटॉल", "ಡೆಟಾಲ್"]),
    (26, "Surf Excel 1kg", 140, "Home care", ["surf excel", "surf", "detergent", "washing powder", "सर्फ", "ಸರ್ಫ್"]),
    (27, "Vim Bar", 10, "Home care", ["vim", "vim bar", "dish soap", "bartan sabun"]),
    (28, "Colgate 100g", 55, "Personal care", ["colgate", "toothpaste", "टूथपेस्ट", "ಟೂತ್ ಪೇಸ್ಟ್"]),
    (29, "Lifebuoy Soap", 35, "Personal care", ["soap", "sabun", "साबुन", "lifebuoy", "ಸೋಪ್"]),
    (30, "Onion 1kg", 40, "Vegetables", ["onion", "onions", "pyaz", "pyaaz", "प्याज", "eerulli", "ಈರುಳ್ಳಿ"]),
    (31, "Tomato 1kg", 30, "Vegetables", ["tomato", "tomatoes", "tamatar", "टमाटर", "ಟೊಮೇಟೊ"]),
    (32, "Coriander Bunch", 10, "Vegetables", ["coriander", "dhaniya", "धनिया", "kothambari", "ಕೊತ್ತಂಬರಿ"]),
    (33, "Peanut Butter 350g", 180, "Health", ["peanut butter", "पीनट बटर", "ಪೀನಟ್ ಬಟರ್"]),
    (34, "Quinoa 500g", 220, "Health", ["quinoa", "kinwa", "किनोआ", "ಕ್ವಿನೋವಾ"]),
    (35, "Idli Dosa Batter 1kg", 70, "Ready to cook", ["idli batter", "dosa batter", "dose hittu", "batter", "ಇಡ್ಲಿ ಹಿಟ್ಟು", "ದೋಸೆ ಹಿಟ್ಟು"]),
    (36, "AA Batteries (2)", 40, "General", ["battery", "batteries", "cell", "aa battery", "बैटरी", "ಬ್ಯಾಟರಿ"]),
    (37, "Candles (pack of 6)", 30, "General", ["candle", "candles", "mombatti", "मोमबत्ती", "ಮೇಣದಬತ್ತಿ"]),
    (38, "Protein Bar", 60, "Health", ["protein bar", "प्रोटीन बार", "ಪ್ರೋಟೀನ್ ಬಾರ್"]),
]

# Which shops stock which products. Oat milk / quinoa only at Green Leaf (outside the
# 500 m radius of most shops); nobody stocks Greek yogurt or protein bars.
_COMMON = [1, 4, 7, 9, 10, 12, 13, 14, 15, 16, 17, 18, 21, 22, 23, 24, 27, 28, 29]
INVENTORY = {
    1: _COMMON + [6, 19, 26, 30, 31],
    2: _COMMON + [5, 6, 8, 11, 19, 25, 26, 36],
    3: _COMMON + [11, 20, 30, 31, 32, 35],
    4: _COMMON + [5, 8, 19, 25, 26, 33, 37],
    5: _COMMON + [20, 30, 31, 32, 35, 36, 37],
    6: [1, 2, 4, 5, 8, 9, 19, 20, 24, 33, 34],
}

# Relative weights for synthetic "customer asked, shop didn't have it" history.
DEMAND_WEIGHTS = {
    2: 9, 3: 7, 11: 6, 38: 5, 34: 3, 33: 3, 25: 4, 8: 4, 5: 4, 35: 3,
    36: 2, 37: 2, 19: 2, 20: 2, 6: 3, 32: 2, 26: 2,
}

import sqlite3
from functools import wraps
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify

app = Flask(__name__)
DB_NAME = "grocery.db"
app.secret_key = "supersecretkey"  # Change this to a strong secret in production

# --- Admin Credentials ---
ADMIN_USER = "subhrajitbehera153"
ADMIN_PASS = "password"


# --- Database Setup ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS locations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS shops (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    location_id INTEGER,
                    FOREIGN KEY(location_id) REFERENCES locations(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    price REAL NOT NULL,
                    photo TEXT,
                    shop_id INTEGER,
                    is_out_of_stock INTEGER DEFAULT 0,
                    FOREIGN KEY(shop_id) REFERENCES shops(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_name TEXT NOT NULL,
                    customer_address TEXT NOT NULL,
                    mobile TEXT,
                    date TEXT NOT NULL,
                    status TEXT DEFAULT 'Pending')''')
    c.execute('''CREATE TABLE IF NOT EXISTS order_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER,
                    item_id INTEGER,
                    quantity INTEGER,
                    FOREIGN KEY(order_id) REFERENCES orders(id),
                    FOREIGN KEY(item_id) REFERENCES items(id))''')

    # Ensure is_out_of_stock column exists for pre-existing databases
    try:
        c.execute("ALTER TABLE items ADD COLUMN is_out_of_stock INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


init_db()


# -----------------------
# Authentication Helpers & Routes
# -----------------------
def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("login"))
        return func(*args, **kwargs)

    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == ADMIN_USER and password == ADMIN_PASS:
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))
        else:
            return render_template("login.html", error="Invalid credentials")
    return render_template("login.html", error=None)


@app.route("/logout")
def logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("login"))


# -----------------------
# User Routes
# -----------------------
@app.route("/")
def index():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM locations")
    locations = c.fetchall()
    conn.close()
    return render_template("locations.html", locations=locations)


@app.route("/location/<int:loc_id>")
def location(loc_id):
    search_query = request.args.get("q", "").lower()

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""SELECT items.id, items.name, items.category, items.price, items.photo, items.is_out_of_stock
                 FROM items
                 LEFT JOIN shops ON items.shop_id = shops.id
                 WHERE shops.location_id=?""", (loc_id,))
    items = c.fetchall()
    conn.close()

    if search_query:
        items = [
            item for item in items 
            if search_query in item[1].lower() or search_query in item[2].lower()
        ]

    categories = {}
    for item in items:
        cat = item[2]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(item)

    return render_template("items.html", categories=categories, search_query=search_query, loc_id=loc_id)


# -----------------------
# Cart Routes
# -----------------------
@app.route("/update_cart/<int:item_id>/<action>")
def update_cart(item_id, action):
    cart = session.get("cart")
    if cart is None or not isinstance(cart, dict):
        cart = {}

    key = str(item_id)

    if action == "add":
        cart[key] = cart.get(key, 0) + 1
    elif action == "remove":
        if key in cart:
            cart[key] -= 1
            if cart[key] <= 0:
                del cart[key]

    session["cart"] = cart

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, name, price FROM items WHERE id=?", (item_id,))
    item = c.fetchone()
    conn.close()

    qty = cart.get(key, 0)
    subtotal = qty * item[2] if item else 0

    return jsonify({
        "item_id": item_id,
        "qty": qty,
        "subtotal": subtotal
    })


@app.route("/cart")
def view_cart():
    cart = session.get("cart")
    if cart is None or not isinstance(cart, dict):
        cart = {}
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    items = []
    total = 0
    for item_id_str, qty in cart.items():
        item_id = int(item_id_str)
        c.execute("SELECT id, name, price FROM items WHERE id=?", (item_id,))
        item = c.fetchone()
        if item:
            items.append((item[0], item[1], item[2], qty))
            total += item[2] * qty
    conn.close()
    return render_template("cart.html", items=items, total=total)


@app.route("/place_order", methods=["POST"])
def place_order():
    customer_name = request.form.get("name", "")
    customer_address = request.form.get("address", "")
    mobile = request.form.get("mobile", "")
    cart = session.get("cart")
    if cart is None or not isinstance(cart, dict) or not cart:
        return redirect(url_for("view_cart"))

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    order_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO orders (customer_name, customer_address, mobile, date) VALUES (?, ?, ?, ?)",
              (customer_name, customer_address, mobile, order_date))
    order_id = c.lastrowid

    for item_id_str, qty in cart.items():
        item_id = int(item_id_str)
        c.execute("INSERT INTO order_items (order_id, item_id, quantity) VALUES (?, ?, ?)",
                  (order_id, item_id, qty))

    conn.commit()
    conn.close()
    session["cart"] = {}

    return redirect(url_for("order_success", order_id=order_id))


@app.route("/order_success/<int:order_id>")
def order_success(order_id):
    return f"Order #{order_id} placed successfully!"


# -----------------------
# Admin Routes (protected)
# -----------------------
@app.route("/admin", methods=["GET", "POST"])
@admin_required
def admin():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if request.method == "POST":
        form_type = request.form.get("form_type", "")
        if form_type == "location":
            name = request.form.get("name", "")
            if name:
                c.execute("INSERT INTO locations (name) VALUES (?)", (name,))
        elif form_type == "shop":
            name = request.form.get("name", "")
            loc_id = request.form.get("location_id", "")
            if name and loc_id:
                try:
                    loc_id_int = int(loc_id)
                except ValueError:
                    loc_id_int = None
                c.execute("INSERT INTO shops (name, location_id) VALUES (?, ?)", (name, loc_id_int))
        elif form_type == "item":
            name = request.form.get("name", "")
            category = request.form.get("category", "")
            price = request.form.get("price", "")
            photo = request.form.get("photo", "")
            shop_id = request.form.get("shop_id", "")
            is_out_of_stock = 1 if request.form.get("is_out_of_stock") else 0
            if name and category and price and shop_id:
                try:
                    price_val = float(price)
                except ValueError:
                    price_val = 0.0
                try:
                    shop_id_val = int(shop_id)
                except ValueError:
                    shop_id_val = None
                c.execute("""INSERT INTO items (name, category, price, photo, shop_id, is_out_of_stock) 
                             VALUES (?, ?, ?, ?, ?, ?)""",
                          (name, category, price_val, photo, shop_id_val, is_out_of_stock))
        conn.commit()

    c.execute("SELECT * FROM locations")
    locations = c.fetchall()
    c.execute("SELECT * FROM shops")
    shops = c.fetchall()
    c.execute("""SELECT items.id, items.name, items.category, items.price, items.photo,
                        shops.name, locations.name, items.is_out_of_stock
                 FROM items
                 LEFT JOIN shops ON items.shop_id = shops.id
                 LEFT JOIN locations ON shops.location_id = locations.id""")
    items = c.fetchall()
    conn.close()
    return render_template("admin.html", locations=locations, shops=shops, items=items)


@app.route("/toggle_stock/<int:item_id>", methods=["POST", "GET"])
@admin_required
def toggle_stock(item_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE items SET is_out_of_stock = CASE WHEN is_out_of_stock = 1 THEN 0 ELSE 1 END WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))


@app.route("/edit_item/<int:item_id>", methods=["GET", "POST"])
@admin_required
def edit_item(item_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if request.method == "POST":
        c.execute("SELECT * FROM items WHERE id=?", (item_id,))
        existing = c.fetchone()
        
        if existing:
            existing_name = existing[1]
            existing_category = existing[2]
            existing_price = existing[3]
            existing_photo = existing[4]
            existing_shop_id = existing[5]
            existing_is_out = existing[6] if len(existing) > 6 else 0
        else:
            existing_name = ""
            existing_category = ""
            existing_price = 0.0
            existing_photo = ""
            existing_shop_id = None
            existing_is_out = 0

        name_raw = request.form.get("name")
        category_raw = request.form.get("category")
        price_raw = request.form.get("price")
        photo_raw = request.form.get("photo")
        shop_id_raw = request.form.get("shop_id")
        is_out_of_stock = 1 if request.form.get("is_out_of_stock") else 0

        name = name_raw if name_raw is not None and name_raw != "" else existing_name
        category = category_raw if category_raw is not None and category_raw != "" else existing_category

        if price_raw is None or price_raw == "":
            price = existing_price
        else:
            try:
                price = float(price_raw)
            except ValueError:
                price = existing_price

        photo = photo_raw if photo_raw is not None and photo_raw != "" else existing_photo

        if shop_id_raw is None or shop_id_raw == "":
            shop_id = existing_shop_id
        else:
            try:
                shop_id = int(shop_id_raw)
            except ValueError:
                shop_id = existing_shop_id

        c.execute("""UPDATE items 
                     SET name=?, category=?, price=?, photo=?, shop_id=?, is_out_of_stock=? 
                     WHERE id=?""",
                  (name, category, float(price), photo, shop_id, is_out_of_stock, item_id))
        conn.commit()
        conn.close()
        return redirect(url_for("admin"))
    else:
        c.execute("SELECT * FROM items WHERE id=?", (item_id,))
        item = c.fetchone()
        c.execute("SELECT * FROM shops")
        shops = c.fetchall()
        conn.close()
        return render_template("edit_item.html", item=item, shops=shops)


@app.route("/delete_item/<int:item_id>")
@admin_required
def delete_item(item_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM items WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))


@app.route("/delete_shop/<int:shop_id>")
@admin_required
def delete_shop(shop_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # First delete items associated with this shop
    c.execute("DELETE FROM items WHERE shop_id=?", (shop_id,))
    # Delete the shop
    c.execute("DELETE FROM shops WHERE id=?", (shop_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))


@app.route("/delete_location/<int:location_id>")
@admin_required
def delete_location(location_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # 1. Delete items that belong to any shops in this location
    c.execute("DELETE FROM items WHERE shop_id IN (SELECT id FROM shops WHERE location_id=?)", (location_id,))
    # 2. Delete shops in this location
    c.execute("DELETE FROM shops WHERE location_id=?", (location_id,))
    # 3. Delete the location itself
    c.execute("DELETE FROM locations WHERE id=?", (location_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))


@app.route("/admin/orders")
@admin_required
def admin_orders():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""SELECT id, date, customer_name, customer_address, mobile, status
                 FROM orders ORDER BY date DESC""")
    orders = c.fetchall()
    conn.close()
    return render_template("orders.html", orders=orders)


@app.route("/admin/order/<int:order_id>")
@admin_required
def order_details(order_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""SELECT items.name, order_items.quantity, items.price,
                        (order_items.quantity * items.price) AS subtotal
                 FROM order_items
                 LEFT JOIN items ON order_items.item_id = items.id
                 WHERE order_items.order_id=?""", (order_id,))
    items = c.fetchall()
    conn.close()
    return render_template("order_details.html", order_id=order_id, items=items)


if __name__ == "__main__":
    app.run(debug=True)
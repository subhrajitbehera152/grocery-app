import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from datetime import datetime

app = Flask(__name__)
DB_NAME = "grocery.db"
app.secret_key = "supersecretkey"

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
    conn.commit()
    conn.close()

init_db()

# --- User Routes ---
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
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""SELECT items.id, items.name, items.category, items.price, items.photo
                 FROM items
                 LEFT JOIN shops ON items.shop_id = shops.id
                 WHERE shops.location_id=?""", (loc_id,))
    items = c.fetchall()
    conn.close()

    categories = {}
    for item in items:
        cat = item[2]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(item)
    return render_template("items.html", categories=categories)

# --- Cart Routes ---
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
    customer_name = request.form["name"]
    customer_address = request.form["address"]
    mobile = request.form["mobile"]
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

# --- Admin Routes ---
@app.route("/admin", methods=["GET", "POST"])
def admin():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if request.method == "POST":
        form_type = request.form["form_type"]
        if form_type == "location":
            name = request.form["name"]
            c.execute("INSERT INTO locations (name) VALUES (?)", (name,))
        elif form_type == "shop":
            name = request.form["name"]
            loc_id = request.form["location_id"]
            c.execute("INSERT INTO shops (name, location_id) VALUES (?, ?)", (name, loc_id))
        elif form_type == "item":
            name = request.form["name"]
            category = request.form["category"]
            price = request.form["price"]
            photo = request.form["photo"]
            shop_id = request.form["shop_id"]
            c.execute("INSERT INTO items (name, category, price, photo, shop_id) VALUES (?, ?, ?, ?, ?)",
                      (name, category, price, photo, shop_id))
        conn.commit()
        conn.close()
        return redirect(url_for("admin"))

    c.execute("SELECT * FROM locations")
    locations = c.fetchall()
    c.execute("SELECT * FROM shops")
    shops = c.fetchall()
    c.execute("""SELECT items.id, items.name, items.category, items.price, items.photo,
                        shops.name, locations.name
                 FROM items
                 LEFT JOIN shops ON items.shop_id = shops.id
                 LEFT JOIN locations ON shops.location_id = locations.id""")
    items = c.fetchall()
    conn.close()
    return render_template("admin.html", locations=locations, shops=shops, items=items)

@app.route("/edit_item/<int:item_id>", methods=["GET", "POST"])
def edit_item(item_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if request.method == "POST":
        new_price = request.form["price"]
        c.execute("UPDATE items SET price=? WHERE id=?", (new_price, item_id))
        conn.commit()
        conn.close()
        return redirect(url_for("admin"))
    else:
        c.execute("SELECT * FROM items WHERE id=?", (item_id,))
        item = c.fetchone()
        conn.close()
        return render_template("edit_item.html", item=item)

@app.route("/delete_item/<int:item_id>")
def delete_item(item_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM items WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))

@app.route("/admin/orders")
def admin_orders():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""SELECT id, date, customer_name, customer_address, mobile
                 FROM orders""")
    orders = c.fetchall()
    conn.close()
    return render_template("orders.html", orders=orders)

@app.route("/admin/order/<int:order_id>")
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

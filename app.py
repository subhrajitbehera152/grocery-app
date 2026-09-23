
import sqlite3
import os

from functools import wraps
from datetime import datetime, timedelta
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify
)

app = Flask(__name__)

# -----------------------
# Configuration
# -----------------------

DB_NAME = "grocery.db"

# For production, configure these using environment variables.
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "change-this-secret-key-before-production"
)

ADMIN_USER = os.environ.get(
    "ADMIN_USER",
    "subhrajitbehera153"
)

ADMIN_PASS = os.environ.get(
    "ADMIN_PASS",
    "password"
)

VALID_ORDER_STATUSES = (
    "Pending",
    "In Progress",
    "On the way",
    "Completed"
)


# -----------------------
# Database Helper
# -----------------------

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# -----------------------
# Order Number Helpers
# -----------------------

def generate_order_number(c):
    """
    Generate a unique formatted order number.

    Format:
    DMJ + hour + minute + second + year + day + month + sum(HH+MM+SS)
    """

    offset = 0

    while True:
        generated_time = datetime.now() + timedelta(seconds=offset)

        hour = generated_time.hour
        minute = generated_time.minute
        second = generated_time.second

        time_sum = hour + minute + second

        order_number = (
            "DMJ"
            + generated_time.strftime("%H%M%S%Y%d%m")
            + str(time_sum)
        )

        c.execute("""
            SELECT 1
            FROM orders
            WHERE order_number = ?
        """, (order_number,))

        if not c.fetchone():
            return order_number

        offset += 1


def get_internal_order_id(c, order_ref):
    """
    Resolve a formatted order number to the internal numeric key.

    Numeric references are also accepted for compatibility with
    older links that may still exist.
    """

    c.execute("""
        SELECT id
        FROM orders
        WHERE order_number = ?
    """, (str(order_ref),))

    row = c.fetchone()

    if row:
        return row[0]

    # Backward compatibility for old numeric order URLs.
    if str(order_ref).isdigit():
        c.execute("""
            SELECT id
            FROM orders
            WHERE id = ?
        """, (int(order_ref),))

        row = c.fetchone()

        if row:
            return row[0]

    return None


def get_order_number(c, internal_order_id):
    """Return the formatted order number for an internal database ID."""

    c.execute("""
        SELECT order_number
        FROM orders
        WHERE id = ?
    """, (internal_order_id,))

    row = c.fetchone()

    if row and row[0]:
        return row[0]

    return str(internal_order_id)


# -----------------------
# Database Setup
# -----------------------

def init_db():
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            location_id INTEGER,
            FOREIGN KEY(location_id) REFERENCES locations(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL,
            photo TEXT,
            shop_id INTEGER,
            is_out_of_stock INTEGER DEFAULT 0,
            FOREIGN KEY(shop_id) REFERENCES shops(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            customer_address TEXT NOT NULL,
            mobile TEXT,
            date TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',
            order_number TEXT UNIQUE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            item_id INTEGER,
            quantity INTEGER,
            FOREIGN KEY(order_id) REFERENCES orders(id),
            FOREIGN KEY(item_id) REFERENCES items(id)
        )
    """)

    # Add is_out_of_stock to older databases if necessary.
    try:
        c.execute("""
            ALTER TABLE items
            ADD COLUMN is_out_of_stock INTEGER DEFAULT 0
        """)
    except sqlite3.OperationalError:
        pass

    # Add status to older orders tables if necessary.
    try:
        c.execute("""
            ALTER TABLE orders
            ADD COLUMN status TEXT DEFAULT 'Pending'
        """)
    except sqlite3.OperationalError:
        pass

    # Add order_number to older orders tables if necessary.
    try:
        c.execute("""
            ALTER TABLE orders
            ADD COLUMN order_number TEXT
        """)
    except sqlite3.OperationalError:
        pass

    # Assign formatted order numbers to existing orders that
    # do not already have one.
    c.execute("""
        SELECT id
        FROM orders
        WHERE order_number IS NULL
           OR order_number = ''
        ORDER BY id
    """)

    old_orders = c.fetchall()

    for row in old_orders:
        internal_order_id = row[0]
        order_number = generate_order_number(c)

        c.execute("""
            UPDATE orders
            SET order_number = ?
            WHERE id = ?
        """, (
            order_number,
            internal_order_id
        ))

    conn.commit()
    conn.close()


init_db()


# -----------------------
# Authentication Helpers
# -----------------------

def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("login"))

        return func(*args, **kwargs)

    return wrapper


# -----------------------
# Authentication Routes
# -----------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if username == ADMIN_USER and password == ADMIN_PASS:
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))

        return render_template(
            "login.html",
            error="Invalid credentials"
        )

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

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT * FROM locations")
    locations = c.fetchall()

    conn.close()

    return render_template(
        "locations.html",
        locations=locations
    )


@app.route("/location/<int:loc_id>")
def location(loc_id):

    search_query = request.args.get("q", "").lower()

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("""
        SELECT
            items.id,
            items.name,
            items.category,
            items.price,
            items.photo,
            items.is_out_of_stock
        FROM items
        LEFT JOIN shops ON items.shop_id = shops.id
        WHERE shops.location_id = ?
    """, (loc_id,))

    items = c.fetchall()

    conn.close()

    if search_query:
        items = [
            item for item in items
            if search_query in item[1].lower()
            or search_query in item[2].lower()
        ]

    categories = {}

    for item in items:

        cat = item[2]

        if cat not in categories:
            categories[cat] = []

        categories[cat].append(item)

    return render_template(
        "items.html",
        categories=categories,
        search_query=search_query,
        loc_id=loc_id
    )


# -----------------------
# Cart Routes
# -----------------------

@app.route("/update_cart/<int:item_id>/<action>")
def update_cart(item_id, action):

    cart = session.get("cart")

    if cart is None or not isinstance(cart, dict):
        cart = {}

    key = str(item_id)

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("""
        SELECT id, name, price, is_out_of_stock
        FROM items
        WHERE id = ?
    """, (item_id,))

    item = c.fetchone()

    conn.close()

    if not item:
        return jsonify({
            "error": "Item not found",
            "item_id": item_id
        }), 404

    if action == "add":

        if item[3]:
            return jsonify({
                "error": "Out of Stock",
                "item_id": item_id,
                "qty": cart.get(key, 0),
                "subtotal": cart.get(key, 0) * item[2],
                "out_of_stock": True
            }), 409

        cart[key] = cart.get(key, 0) + 1

    elif action == "remove":

        if key in cart:

            cart[key] -= 1

            if cart[key] <= 0:
                del cart[key]

    else:
        return jsonify({
            "error": "Invalid cart action"
        }), 400

    session["cart"] = cart

    qty = cart.get(key, 0)

    return jsonify({
        "item_id": item_id,
        "qty": qty,
        "subtotal": qty * item[2],
        "out_of_stock": bool(item[3])
    })


@app.route("/cart")
def view_cart():

    cart = session.get("cart")

    if cart is None or not isinstance(cart, dict):
        cart = {}

    conn = get_db_connection()
    c = conn.cursor()

    items = []
    total = 0

    for item_id_str, qty in cart.items():

        try:
            item_id = int(item_id_str)
            qty = int(qty)
        except (TypeError, ValueError):
            continue

        if qty <= 0:
            continue

        c.execute("""
            SELECT id, name, price
            FROM items
            WHERE id = ?
        """, (item_id,))

        item = c.fetchone()

        if item:
            items.append((
                item[0],
                item[1],
                item[2],
                qty
            ))

            total += item[2] * qty

    conn.close()

    return render_template(
        "cart.html",
        items=items,
        total=total
    )


@app.route("/place_order", methods=["POST"])
def place_order():

    customer_name = request.form.get("name", "").strip()
    customer_address = request.form.get("address", "").strip()
    house_landmark = request.form.get("house_landmark", "").strip()
    mobile = request.form.get("mobile", "").strip()

    # Combine house/landmark and street address.
    full_address = ", ".join(
        part for part in (house_landmark, customer_address) if part
    )

    cart = session.get("cart")

    if (
        not isinstance(cart, dict)
        or not cart
        or not customer_name
        or not customer_address
        or not house_landmark
    ):
        return redirect(url_for("view_cart"))

    conn = get_db_connection()
    c = conn.cursor()

    try:

        # Validate all cart entries and inventory before creating
        # the order.
        validated_items = []

        for item_id_str, qty in cart.items():

            try:
                item_id = int(item_id_str)
                quantity = int(qty)
            except (TypeError, ValueError):
                return redirect(url_for("view_cart"))

            if quantity <= 0:
                return redirect(url_for("view_cart"))

            c.execute("""
                SELECT id, is_out_of_stock
                FROM items
                WHERE id = ?
            """, (item_id,))

            stock_row = c.fetchone()

            if not stock_row or stock_row[1]:
                return redirect(url_for("view_cart"))

            validated_items.append((item_id, quantity))

        order_date = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        # Generate the formatted order number.
        order_number = generate_order_number(c)

        c.execute("""
            INSERT INTO orders (
                customer_name,
                customer_address,
                mobile,
                date,
                status,
                order_number
            )
            VALUES (?, ?, ?, ?, 'Pending', ?)
        """, (
            customer_name,
            full_address,
            mobile,
            order_date,
            order_number
        ))

        # Keep the numeric ID internally for order_items relations.
        internal_order_id = c.lastrowid

        for item_id, quantity in validated_items:

            c.execute("""
                INSERT INTO order_items (
                    order_id,
                    item_id,
                    quantity
                )
                VALUES (?, ?, ?)
            """, (
                internal_order_id,
                item_id,
                quantity
            ))

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    session["cart"] = {}

    # Use the formatted order number in the customer-facing URL.
    return redirect(
        url_for("track_order", order_id=order_number)
    )


# -----------------------
# Order Tracking
# -----------------------

@app.route("/track/<string:order_id>")
def track_order(order_id):

    conn = get_db_connection()
    c = conn.cursor()

    # Accept formatted order numbers and legacy numeric references.
    internal_order_id = get_internal_order_id(c, order_id)

    if internal_order_id is None:
        conn.close()
        return "Order not found", 404

    # Retrieve the order using its internal database key.
    c.execute("""
        SELECT
            id,
            customer_name,
            customer_address,
            mobile,
            date,
            COALESCE(status, 'Pending'),
            order_number
        FROM orders
        WHERE id = ?
    """, (internal_order_id,))

    order_row = c.fetchone()

    if not order_row:
        conn.close()
        return "Order not found", 404

    formatted_order_number = (
        order_row[6] or str(order_row[0])
    )

    # Retrieve ordered products and their prices.
    c.execute("""
        SELECT
            COALESCE(items.name, 'Deleted item'),
            order_items.quantity,
            COALESCE(items.price, 0),
            COALESCE(order_items.quantity * items.price, 0)
        FROM order_items
        LEFT JOIN items
            ON order_items.item_id = items.id
        WHERE order_items.order_id = ?
        ORDER BY order_items.id
    """, (internal_order_id,))

    item_rows = c.fetchall()

    conn.close()

    # Convert database tuples to dictionaries expected by track.html.
    items = [
        {
            "name": row[0],
            "quantity": row[1],
            "price": row[2],
            "subtotal": row[3]
        }
        for row in item_rows
    ]

    subtotal = sum(item["subtotal"] or 0 for item in items)

    # Delivery fee: ₹30 below ₹150; free at/above ₹150.
    delivery_fee = 30 if 0 < subtotal < 150 else 0
    total = subtotal + delivery_fee

    # Adapt status values to tracking-page progress labels.
    status = order_row[5]

    if status == "Pending":
        display_status = "Order Placed"
    elif status == "In Progress":
        display_status = "Preparing"
    elif status == "On the way":
        display_status = "On the way"
    elif status == "Completed":
        display_status = "Delivered"
    else:
        display_status = status

    order = {
        "id": formatted_order_number,
        "order_number": formatted_order_number,
        "name": order_row[1],
        "house_landmark": "",
        "address": order_row[2],
        "mobile": order_row[3],
        "date": order_row[4],
        "status": display_status,
        "subtotal": subtotal,
        "delivery_fee": delivery_fee,
        "total": total,
        "payment_method": "Not specified"
    }

    # Partner details are not stored in the current database.
    partner = None

    return render_template(
        "track.html",
        order=order,
        items=items,
        partner=partner
    )


# Keep the old order-success URL working.
@app.route("/order_success/<string:order_id>")
def order_success(order_id):

    return redirect(
        url_for("track_order", order_id=order_id)
    )


# -----------------------
# Admin Dashboard
# -----------------------

@app.route("/admin", methods=["GET", "POST"])
@admin_required
def admin():

    conn = get_db_connection()
    c = conn.cursor()

    if request.method == "POST":

        form_type = request.form.get("form_type", "")

        if form_type == "location":

            name = request.form.get("name", "").strip()

            if name:
                c.execute("""
                    INSERT INTO locations (name)
                    VALUES (?)
                """, (name,))

        elif form_type == "shop":

            name = request.form.get("name", "").strip()
            loc_id = request.form.get("location_id", "")

            if name and loc_id:

                try:
                    loc_id_int = int(loc_id)
                except ValueError:
                    loc_id_int = None

                c.execute("""
                    INSERT INTO shops (name, location_id)
                    VALUES (?, ?)
                """, (
                    name,
                    loc_id_int
                ))

        elif form_type == "item":

            name = request.form.get("name", "").strip()
            category = request.form.get("category", "").strip()
            price = request.form.get("price", "")
            photo = request.form.get("photo", "").strip()
            shop_id = request.form.get("shop_id", "")

            is_out_of_stock = (
                1 if request.form.get("is_out_of_stock") else 0
            )

            if name and category and price and shop_id:

                try:
                    price_val = float(price)
                except ValueError:
                    price_val = 0.0

                try:
                    shop_id_val = int(shop_id)
                except ValueError:
                    shop_id_val = None

                c.execute("""
                    INSERT INTO items (
                        name,
                        category,
                        price,
                        photo,
                        shop_id,
                        is_out_of_stock
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    name,
                    category,
                    price_val,
                    photo,
                    shop_id_val,
                    is_out_of_stock
                ))

        conn.commit()

    c.execute("SELECT * FROM locations")
    locations = c.fetchall()

    c.execute("SELECT * FROM shops")
    shops = c.fetchall()

    c.execute("""
        SELECT
            items.id,
            items.name,
            items.category,
            items.price,
            items.photo,
            shops.name,
            locations.name,
            items.is_out_of_stock
        FROM items
        LEFT JOIN shops ON items.shop_id = shops.id
        LEFT JOIN locations ON shops.location_id = locations.id
    """)

    items = c.fetchall()

    conn.close()

    return render_template(
        "admin.html",
        locations=locations,
        shops=shops,
        items=items
    )


# -----------------------
# Admin Item Routes
# -----------------------

@app.route("/toggle_stock/<int:item_id>", methods=["POST", "GET"])
@admin_required
def toggle_stock(item_id):

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("""
        UPDATE items
        SET is_out_of_stock =
            CASE
                WHEN is_out_of_stock = 1 THEN 0
                ELSE 1
            END
        WHERE id = ?
    """, (item_id,))

    conn.commit()
    conn.close()

    return redirect(url_for("admin"))


@app.route("/edit_item/<int:item_id>", methods=["GET", "POST"])
@admin_required
def edit_item(item_id):

    conn = get_db_connection()
    c = conn.cursor()

    if request.method == "POST":

        c.execute(
            "SELECT id FROM items WHERE id = ?",
            (item_id,)
        )

        if not c.fetchone():
            conn.close()
            return redirect(url_for("admin"))

        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        price_raw = request.form.get("price", "").strip()
        photo = request.form.get("photo", "").strip()
        shop_id_raw = request.form.get("shop_id", "").strip()

        is_out_of_stock = (
            1 if request.form.get("is_out_of_stock") else 0
        )

        try:
            price = float(price_raw)
            shop_id = int(shop_id_raw)

        except (TypeError, ValueError):

            c.execute(
                "SELECT * FROM items WHERE id = ?",
                (item_id,)
            )
            item = c.fetchone()

            c.execute("SELECT * FROM shops")
            shops = c.fetchall()

            conn.close()

            return render_template(
                "edit_item.html",
                item=item,
                shops=shops,
                error="Enter a valid price and shop."
            )

        if not name or not category or price < 0:

            c.execute(
                "SELECT * FROM items WHERE id = ?",
                (item_id,)
            )
            item = c.fetchone()

            c.execute("SELECT * FROM shops")
            shops = c.fetchall()

            conn.close()

            return render_template(
                "edit_item.html",
                item=item,
                shops=shops,
                error=(
                    "Name and category are required; "
                    "price cannot be negative."
                )
            )

        c.execute("""
            UPDATE items
            SET
                name = ?,
                category = ?,
                price = ?,
                photo = ?,
                shop_id = ?,
                is_out_of_stock = ?
            WHERE id = ?
        """, (
            name,
            category,
            price,
            photo,
            shop_id,
            is_out_of_stock,
            item_id
        ))

        conn.commit()
        conn.close()

        return redirect(url_for("admin"))

    c.execute(
        "SELECT * FROM items WHERE id = ?",
        (item_id,)
    )
    item = c.fetchone()

    c.execute("SELECT * FROM shops")
    shops = c.fetchall()

    conn.close()

    if not item:
        return redirect(url_for("admin"))

    return render_template(
        "edit_item.html",
        item=item,
        shops=shops,
        error=None
    )


@app.route("/delete_item/<int:item_id>")
@admin_required
def delete_item(item_id):

    conn = get_db_connection()
    c = conn.cursor()

    c.execute(
        "DELETE FROM items WHERE id = ?",
        (item_id,)
    )

    conn.commit()
    conn.close()

    return redirect(url_for("admin"))


@app.route("/delete_shop/<int:shop_id>")
@admin_required
def delete_shop(shop_id):

    conn = get_db_connection()
    c = conn.cursor()

    # Delete items associated with the shop.
    c.execute(
        "DELETE FROM items WHERE shop_id = ?",
        (shop_id,)
    )

    # Delete the shop.
    c.execute(
        "DELETE FROM shops WHERE id = ?",
        (shop_id,)
    )

    conn.commit()
    conn.close()

    return redirect(url_for("admin"))


@app.route("/delete_location/<int:location_id>")
@admin_required
def delete_location(location_id):

    conn = get_db_connection()
    c = conn.cursor()

    # Delete items belonging to shops in this location.
    c.execute("""
        DELETE FROM items
        WHERE shop_id IN (
            SELECT id
            FROM shops
            WHERE location_id = ?
        )
    """, (location_id,))

    # Delete shops in this location.
    c.execute("""
        DELETE FROM shops
        WHERE location_id = ?
    """, (location_id,))

    # Delete the location.
    c.execute("""
        DELETE FROM locations
        WHERE id = ?
    """, (location_id,))

    conn.commit()
    conn.close()

    return redirect(url_for("admin"))


# -----------------------
# Admin Order Management
# -----------------------

@app.route("/admin/orders")
@admin_required
def admin_orders():

    conn = get_db_connection()
    c = conn.cursor()

    # Select the formatted order number as the first value so
    # templates that display orders[i][0] show the DMJ number.
    c.execute("""
        SELECT
            COALESCE(orders.order_number, CAST(orders.id AS TEXT)),
            orders.date,
            orders.customer_name,
            orders.customer_address,
            orders.mobile,
            COALESCE(orders.status, 'Pending'),
            COUNT(order_items.id) AS item_count,
            COALESCE(
                SUM(order_items.quantity * items.price),
                0
            ) AS total
        FROM orders
        LEFT JOIN order_items
            ON orders.id = order_items.order_id
        LEFT JOIN items
            ON order_items.item_id = items.id
        GROUP BY orders.id
        ORDER BY orders.date DESC, orders.id DESC
    """)

    orders = c.fetchall()

    conn.close()

    return render_template(
        "orders.html",
        orders=orders,
        valid_statuses=VALID_ORDER_STATUSES
    )


# -----------------------
# Order Details
# -----------------------

@app.route("/admin/order/<string:order_id>")
@admin_required
def order_details(order_id):

    conn = get_db_connection()
    c = conn.cursor()

    # Resolve the formatted order number or a legacy numeric reference.
    internal_order_id = get_internal_order_id(c, order_id)

    if internal_order_id is None:
        conn.close()
        return "Order not found", 404

    # Retrieve the order and customer information.
    # The first tuple value is the formatted order number.
    c.execute("""
        SELECT
            COALESCE(order_number, CAST(id AS TEXT)),
            customer_name,
            customer_address,
            mobile,
            date,
            COALESCE(status, 'Pending')
        FROM orders
        WHERE id = ?
    """, (internal_order_id,))

    order = c.fetchone()

    if not order:
        conn.close()
        return "Order not found", 404

    formatted_order_number = order[0]

    # Retrieve the products associated with this order.
    c.execute("""
        SELECT
            COALESCE(items.name, 'Deleted item'),
            order_items.quantity,
            COALESCE(items.price, 0),
            COALESCE(
                order_items.quantity * items.price,
                0
            ) AS subtotal
        FROM order_items
        LEFT JOIN items
            ON order_items.item_id = items.id
        WHERE order_items.order_id = ?
        ORDER BY order_items.id
    """, (internal_order_id,))

    items = c.fetchall()

    # Calculate the total order amount.
    total = sum(
        item[3] or 0
        for item in items
    )

    conn.close()

    return render_template(
        "order_details.html",
        order=order,
        order_id=formatted_order_number,
        items=items,
        total=total,
        valid_statuses=VALID_ORDER_STATUSES
    )


# -----------------------
# Update Order Status
# -----------------------

@app.route(
    "/admin/order/<string:order_id>/update-status",
    methods=["POST"]
)
@admin_required
def update_order_status(order_id):

    status = request.form.get("status", "").strip()

    # Only permit the supported status values.
    if status not in VALID_ORDER_STATUSES:
        return "Invalid order status", 400

    conn = get_db_connection()
    c = conn.cursor()

    internal_order_id = get_internal_order_id(c, order_id)

    if internal_order_id is None:
        conn.close()
        return "Order not found", 404

    c.execute("""
        UPDATE orders
        SET status = ?
        WHERE id = ?
    """, (
        status,
        internal_order_id
    ))

    updated = c.rowcount

    conn.commit()
    conn.close()

    if not updated:
        return "Order not found", 404

    return redirect(
        url_for(
            "order_details",
            order_id=order_id
        )
    )


# -----------------------
# Delete Order
# -----------------------

@app.route(
    "/admin/order/<string:order_id>/delete",
    methods=["POST"]
)
@admin_required
def delete_order(order_id):

    conn = get_db_connection()

    try:

        conn.execute("BEGIN")

        c = conn.cursor()

        internal_order_id = get_internal_order_id(c, order_id)

        if internal_order_id is None:
            conn.rollback()
            return "Order not found", 404

        # Delete the associated order items first.
        c.execute("""
            DELETE FROM order_items
            WHERE order_id = ?
        """, (internal_order_id,))

        # Delete the order itself.
        c.execute("""
            DELETE FROM orders
            WHERE id = ?
        """, (internal_order_id,))

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return redirect(url_for("admin_orders"))


# -----------------------
# Run Application
# -----------------------

if __name__ == "__main__":
    app.run(debug=True)
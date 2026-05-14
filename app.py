from flask import Flask, render_template, request, jsonify, send_file
import io
import json
import os
import qrcode

app = Flask(__name__, template_folder='templates')

DATABASE_URL = os.environ.get('DATABASE_URL', '')
IS_PG = bool(DATABASE_URL)

if IS_PG:
    import psycopg2
    import psycopg2.extras
    import urllib.parse

    def get_db():
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn

    def fetchall(cursor):
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def fetchone(cursor):
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    def db_execute(conn, sql, params=None):
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur

    def db_last_id(cur):
        return cur.fetchone()[0]

    PG_SQL = {
        'init_dishes': '''CREATE TABLE IF NOT EXISTS dishes (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            price DOUBLE PRECISION NOT NULL,
            description TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            category TEXT DEFAULT '未分类'
        )''',
        'init_orders': '''CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            items TEXT NOT NULL,
            total DOUBLE PRECISION NOT NULL,
            payment_method TEXT DEFAULT '微信支付',
            status TEXT DEFAULT 'paid',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''',
        'insert_dish': "INSERT INTO dishes (name, price, description, image_url, category) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        'insert_order': "INSERT INTO orders (items, total, payment_method, status) VALUES (%s, %s, %s, %s) RETURNING id",
    }
else:
    import sqlite3

    def get_db():
        conn = sqlite3.connect('menu.db')
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def fetchall(cursor):
        return [dict(row) for row in cursor.fetchall()]

    def fetchone(cursor):
        row = cursor.fetchone()
        return dict(row) if row else None

    def db_execute(conn, sql, params=None):
        sql = sql.replace('%s', '?')
        cur = conn.cursor()
        cur.execute(sql, params or ())
        return cur

    def db_last_id(cur, conn):
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    PG_SQL = {}


def init_db():
    conn = get_db()
    if IS_PG:
        db_execute(conn, PG_SQL['init_dishes'])
        db_execute(conn, PG_SQL['init_orders'])
    else:
        db_execute(conn, '''CREATE TABLE IF NOT EXISTS dishes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            description TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            category TEXT DEFAULT '未分类'
        )''')
        db_execute(conn, '''CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            items TEXT NOT NULL,
            total REAL NOT NULL,
            payment_method TEXT DEFAULT '微信支付',
            status TEXT DEFAULT 'paid',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
    # 预置5条示例数据
    cur = db_execute(conn, "SELECT COUNT(*) AS cnt FROM dishes")
    count = fetchone(cur)['cnt']
    if count == 0:
        samples = [
            ('宫保鸡丁', 32.0, '鸡肉丁与花生米爆炒，麻辣鲜香', 'https://i.imgur.com/0X0X0X0.jpg', '热菜'),
            ('麻婆豆腐', 22.0, '嫩豆腐配麻辣肉末，川味经典', 'https://i.imgur.com/1Y1Y1Y1.jpg', '热菜'),
            ('拍黄瓜', 12.0, '蒜泥醋汁凉拌黄瓜，清脆爽口', 'https://i.imgur.com/2Z2Z2Z2.jpg', '凉菜'),
            ('蛋炒饭', 15.0, '粒粒分明的家常蛋炒饭', 'https://i.imgur.com/3A3A3A3.jpg', '主食'),
            ('酸梅汤', 8.0, '冰镇酸梅汤，生津解渴', 'https://i.imgur.com/4B4B4B4.jpg', '饮品'),
        ]
        for s in samples:
            db_execute(conn,
                "INSERT INTO dishes (name, price, description, image_url, category) VALUES (%s, %s, %s, %s, %s)",
                s)
    conn.commit()
    conn.close()


# ========== 页面路由 ==========

@app.route('/debug')
def debug():
    import os as _os
    files = _os.listdir(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'templates'))
    cwd = _os.getcwd()
    app_root = _os.path.dirname(_os.path.abspath(__file__))
    return jsonify({
        'cwd': cwd,
        'app_root': app_root,
        'template_folder_exists': _os.path.exists('templates'),
        'template_fullpath': _os.path.join(app_root, 'templates'),
        'template_fullpath_exists': _os.path.exists(_os.path.join(app_root, 'templates')),
        'files_in_templates': files,
        'is_pg': IS_PG,
    })

@app.route('/')
def menu():
    conn = get_db()
    cur = db_execute(conn, "SELECT * FROM dishes ORDER BY category, id")
    dishes = fetchall(cur)
    cur = db_execute(conn, "SELECT DISTINCT category FROM dishes ORDER BY category")
    categories = fetchall(cur)
    conn.close()
    return render_template('menu.html', dishes=dishes, categories=categories)


@app.route('/admin')
def admin():
    conn = get_db()
    cur = db_execute(conn, "SELECT * FROM dishes ORDER BY category, id")
    dishes = fetchall(cur)
    conn.close()
    return render_template('admin.html', dishes=dishes)


# ========== 菜品 API ==========

@app.route('/api/dishes', methods=['GET'])
def api_get_dishes():
    conn = get_db()
    cur = db_execute(conn, "SELECT * FROM dishes ORDER BY category, id")
    dishes = fetchall(cur)
    conn.close()
    return jsonify(dishes)


@app.route('/api/dishes', methods=['POST'])
def api_add_dish():
    data = request.json
    if not data.get('name') or not data.get('price'):
        return jsonify({'error': '名称和价格不能为空'}), 400
    conn = get_db()
    sql = "INSERT INTO dishes (name, price, description, image_url, category) VALUES (%s, %s, %s, %s, %s)"
    if IS_PG:
        sql += " RETURNING id"
    cur = db_execute(conn, sql,
        (data['name'], float(data['price']), data.get('description', ''),
         data.get('image_url', ''), data.get('category', '未分类')))
    if IS_PG:
        dish_id = db_last_id(cur)
    else:
        dish_id = cur.lastrowid
    conn.commit()
    cur = db_execute(conn, "SELECT * FROM dishes WHERE id = %s", (dish_id,))
    dish = fetchone(cur)
    conn.close()
    return jsonify(dish), 201


@app.route('/api/dishes/<int:dish_id>', methods=['PUT'])
def api_update_dish(dish_id):
    data = request.json
    conn = get_db()
    cur = db_execute(conn, "SELECT * FROM dishes WHERE id = %s", (dish_id,))
    dish = fetchone(cur)
    if not dish:
        conn.close()
        return jsonify({'error': '菜品不存在'}), 404
    db_execute(conn,
        "UPDATE dishes SET name=%s, price=%s, description=%s, image_url=%s, category=%s WHERE id=%s",
        (data.get('name', dish['name']), float(data.get('price', dish['price'])),
         data.get('description', dish['description']), data.get('image_url', dish['image_url']),
         data.get('category', dish['category']), dish_id))
    conn.commit()
    cur = db_execute(conn, "SELECT * FROM dishes WHERE id = %s", (dish_id,))
    updated = fetchone(cur)
    conn.close()
    return jsonify(updated)


@app.route('/api/dishes/<int:dish_id>', methods=['DELETE'])
def api_delete_dish(dish_id):
    conn = get_db()
    db_execute(conn, "DELETE FROM dishes WHERE id = %s", (dish_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ========== 订单 API ==========

@app.route('/api/orders', methods=['GET'])
def api_get_orders():
    conn = get_db()
    cur = db_execute(conn, "SELECT * FROM orders ORDER BY created_at DESC")
    orders = fetchall(cur)
    conn.close()
    return jsonify(orders)


@app.route('/api/orders', methods=['POST'])
def api_create_order():
    data = request.json
    if not data.get('items') or not data.get('total'):
        return jsonify({'error': '订单数据不完整'}), 400
    conn = get_db()
    sql = "INSERT INTO orders (items, total, payment_method, status) VALUES (%s, %s, %s, %s)"
    if IS_PG:
        sql += " RETURNING id"
    cur = db_execute(conn, sql,
        (json.dumps(data['items'], ensure_ascii=False), float(data['total']),
         data.get('payment_method', '微信支付'), 'paid'))
    if IS_PG:
        order_id = db_last_id(cur)
    else:
        order_id = cur.lastrowid
    conn.commit()
    cur = db_execute(conn, "SELECT * FROM orders WHERE id = %s", (order_id,))
    order = fetchone(cur)
    conn.close()
    return jsonify(order), 201


@app.route('/api/orders/<int:order_id>/status', methods=['PUT'])
def api_update_order_status(order_id):
    data = request.json
    conn = get_db()
    db_execute(conn, "UPDATE orders SET status=%s WHERE id=%s",
               (data.get('status', 'cancelled'), order_id))
    conn.commit()
    cur = db_execute(conn, "SELECT * FROM orders WHERE id = %s", (order_id,))
    order = fetchone(cur)
    conn.close()
    if order:
        return jsonify(order)
    return jsonify({'error': '订单不存在'}), 404


# ========== 二维码路由 ==========

@app.route('/qrcode')
def qrcode_image():
    url = request.host_url
    img = qrcode.make(url, border=2)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png', as_attachment=True, download_name='点菜二维码.png')


init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=not IS_PG)

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, make_response
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from database import (
    db, Product, User, CartItem, UserAddress,
    Order, OrderItem, SupportTicket, Review, Favorite, init_db
)
from datetime import datetime
from markupsafe import Markup, escape
import random

app = Flask(__name__)
app.config.from_pyfile('config.py')

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# Фильтр для перевода \n в <br>
@app.template_filter('nl2br')
def nl2br(value):
    if not value:
        return ''
    return Markup(escape(value).replace('\n', '<br>\n'))


with app.app_context():
    try:
        init_db()
        print("База данных успешно инициализирована")
    except Exception as e:
        print(f"Ошибка при инициализации БД: {e}")
        db.create_all()
        init_db()


# Генерация номеров
def generate_order_number():
    return f"ORD-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"


def generate_ticket_number():
    return f"TICKET-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"


# ---------------- Основной каталог ----------------
@app.route('/')
def index():
    category = request.args.get('category', 'all')
    search = request.args.get('search', '')

    query = Product.query.filter_by(available=True)

    if search:
        query = query.filter(
            Product.name.contains(search) |
            Product.description.contains(search) |
            Product.brand.contains(search)
        )

    if category != 'all':
        query = query.filter_by(category=category)

    products = query.all()
    categories = ['all', 'sneakers', 'boots', 'casual', 'sports', 'formal']

    cart_count = 0
    favorite_product_ids = set()
    if current_user.is_authenticated:
        cart_count = CartItem.query.filter_by(user_id=current_user.id).count()
        favorites = Favorite.query.filter_by(user_id=current_user.id).all()
        favorite_product_ids = {f.product_id for f in favorites}

    return render_template(
        'index.html',
        products=products,
        categories=categories,
        current_category=category,
        search=search,
        cart_count=cart_count,
        favorite_product_ids=favorite_product_ids
    )


# ---------------- Карточка товара + отзывы + избранное ----------------
@app.route('/product/<int:product_id>')
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)

    cart_count = 0
    if current_user.is_authenticated:
        cart_count = CartItem.query.filter_by(user_id=current_user.id).count()

    sizes = product.available_sizes.split(',') if product.available_sizes else []

    images = []
    if product.main_image:
        images.append(product.main_image)
    if product.image2:
        images.append(product.image2)
    if product.image3:
        images.append(product.image3)

    # Отзывы
    reviews = Review.query.filter_by(product_id=product.id).order_by(Review.created_at.desc()).all()
    avg_rating = None
    if reviews:
        avg_rating = round(sum(r.rating for r in reviews) / len(reviews), 1)

    user_review = None
    user_has_favorited = False
    if current_user.is_authenticated:
        user_review = Review.query.filter_by(
            user_id=current_user.id,
            product_id=product.id
        ).first()
        user_has_favorited = Favorite.query.filter_by(
            user_id=current_user.id,
            product_id=product.id
        ).first() is not None

    return render_template(
        'product.html',
        product=product,
        sizes=sizes,
        images=images,
        cart_count=cart_count,
        reviews=reviews,
        avg_rating=avg_rating,
        user_review=user_review,
        user_has_favorited=user_has_favorited
    )


@app.route('/product/<int:product_id>/review', methods=['POST'])
@login_required
def add_review(product_id):
    product = Product.query.get_or_404(product_id)
    rating = request.form.get('rating', type=int)
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()

    if not rating or rating < 1 or rating > 5:
        flash('Оценка должна быть от 1 до 5')
        return redirect(url_for('product_detail', product_id=product.id))

    if not content:
        flash('Текст отзыва не может быть пустым')
        return redirect(url_for('product_detail', product_id=product.id))

    review = Review.query.filter_by(
        user_id=current_user.id,
        product_id=product.id
    ).first()

    if review:
        review.rating = rating
        review.title = title
        review.content = content
        review.updated_at = datetime.utcnow()
        msg = 'Отзыв обновлён'
    else:
        review = Review(
            user_id=current_user.id,
            product_id=product.id,
            rating=rating,
            title=title,
            content=content
        )
        db.session.add(review)
        msg = 'Отзыв добавлен'

    try:
        db.session.commit()
        flash(msg)
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при сохранении отзыва: {e}')

    return redirect(url_for('product_detail', product_id=product.id))


# Избранное
@app.route('/favorite/<int:product_id>/toggle', methods=['POST'])
@login_required
def toggle_favorite(product_id):
    product = Product.query.get_or_404(product_id)
    fav = Favorite.query.filter_by(
        user_id=current_user.id,
        product_id=product.id
    ).first()

    if fav:
        db.session.delete(fav)
        action = 'removed'
    else:
        fav = Favorite(user_id=current_user.id, product_id=product.id)
        db.session.add(fav)
        action = 'added'

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при обновлении избранного: {e}')
        return redirect(request.referrer or url_for('product_detail', product_id=product.id))

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'status': 'ok', 'action': action})

    return redirect(request.referrer or url_for('product_detail', product_id=product.id))


# ---------------- Корзина ----------------
@app.route('/add_to_cart', methods=['POST'])
@login_required
def add_to_cart():
    product_id = request.form.get('product_id')
    size = request.form.get('size')
    quantity = int(request.form.get('quantity', 1))

    if not size:
        flash('Пожалуйста, выберите размер')
        return redirect(url_for('product_detail', product_id=product_id))

    product = Product.query.get_or_404(product_id)
    sizes = product.available_sizes.split(',')

    if size not in [s.strip() for s in sizes]:
        flash('Выбранный размер недоступен')
        return redirect(url_for('product_detail', product_id=product_id))

    existing_item = CartItem.query.filter_by(
        user_id=current_user.id,
        product_id=product_id,
        size=size
    ).first()

    if existing_item:
        existing_item.quantity += quantity
    else:
        cart_item = CartItem(
            user_id=current_user.id,
            product_id=product_id,
            size=size,
            quantity=quantity
        )
        db.session.add(cart_item)

    try:
        db.session.commit()
        flash('Товар добавлен в корзину')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при добавлении товара в корзину: {str(e)}')

    return redirect(url_for('product_detail', product_id=product_id))


@app.route('/cart')
@login_required
def cart():
    cart_items = CartItem.query.filter_by(user_id=current_user.id).all()
    total = sum(item.product.price * item.quantity for item in cart_items)
    cart_count = len(cart_items)

    return render_template('cart.html',
                           cart_items=cart_items,
                           total=total,
                           cart_count=cart_count)


@app.route('/update_cart', methods=['POST'])
@login_required
def update_cart():
    item_id = request.form.get('item_id')
    quantity = int(request.form.get('quantity', 1))

    if quantity <= 0:
        CartItem.query.filter_by(id=item_id, user_id=current_user.id).delete()
    else:
        item = CartItem.query.filter_by(id=item_id, user_id=current_user.id).first()
        if item:
            item.quantity = quantity

    try:
        db.session.commit()
        flash('Корзина обновлена')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при обновлении корзины: {str(e)}')

    return redirect(url_for('cart'))


@app.route('/remove_from_cart/<int:item_id>')
@login_required
def remove_from_cart(item_id):
    try:
        CartItem.query.filter_by(id=item_id, user_id=current_user.id).delete()
        db.session.commit()
        flash('Товар удален из корзины')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при удалении товара: {str(e)}')

    return redirect(url_for('cart'))


# ---------------- Оформление заказа ----------------
@app.route('/checkout')
@login_required
def checkout():
    cart_items = CartItem.query.filter_by(user_id=current_user.id).all()

    if not cart_items:
        flash('Ваша корзина пуста')
        return redirect(url_for('cart'))

    total = sum(item.product.price * item.quantity for item in cart_items)
    cart_count = CartItem.query.filter_by(user_id=current_user.id).count()

    # Адреса пользователя
    addresses = UserAddress.query.filter_by(user_id=current_user.id).order_by(
        UserAddress.is_default.desc()
    ).all()

    return render_template('checkout.html',
                           cart_items=cart_items,
                           total=total,
                           addresses=addresses,
                           cart_count=cart_count)


@app.route('/process_order', methods=['POST'])
@login_required
def process_order():
    try:
        cart_items = CartItem.query.filter_by(user_id=current_user.id).all()

        if not cart_items:
            flash('Ваша корзина пуста')
            return redirect(url_for('cart'))

        address_id = request.form.get('address_id')
        payment_method = request.form.get('payment_method', 'cash')
        notes = request.form.get('notes', '')

        shipping_address = ""
        if address_id:
            address = UserAddress.query.filter_by(id=address_id, user_id=current_user.id).first()
            if address:
                shipping_address = f"{address.country}, {address.city}, {address.street}, д. {address.house}"
                if address.apartment:
                    shipping_address += f", кв. {address.apartment}"
                shipping_address += f", {address.postal_code}, {address.full_name}, {address.phone}"
            else:
                flash('Выбранный адрес не найден')
                return redirect(url_for('checkout'))
        else:
            # данные нового адреса
            full_name = request.form.get('full_name')
            phone = request.form.get('phone')
            country = request.form.get('country', 'Россия')
            city = request.form.get('city')
            street = request.form.get('street')
            house = request.form.get('house')
            apartment = request.form.get('apartment', '')
            postal_code = request.form.get('postal_code', '')

            if not all([full_name, phone, country, city, street, house]):
                flash('Заполните все обязательные поля адреса')
                return redirect(url_for('checkout'))

            shipping_address = f"{country}, {city}, {street}, д. {house}"
            if apartment:
                shipping_address += f", кв. {apartment}"
            shipping_address += f", {postal_code}, {full_name}, {phone}"

        total_amount = sum(item.product.price * item.quantity for item in cart_items)
        order = Order(
            user_id=current_user.id,
            order_number=generate_order_number(),
            total_amount=total_amount,
            shipping_address=shipping_address,
            payment_method=payment_method,
            notes=notes
        )
        db.session.add(order)
        db.session.flush()

        for item in cart_items:
            order_item = OrderItem(
                order_id=order.id,
                product_id=item.product_id,
                product_name=item.product.name,
                size=item.size,
                quantity=item.quantity,
                price=item.product.price
            )
            db.session.add(order_item)

        CartItem.query.filter_by(user_id=current_user.id).delete()

        db.session.commit()
        flash(f'Заказ успешно оформлен! Номер заказа: {order.order_number}')
        return redirect(url_for('profile', tab='orders'))

    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при оформлении заказа: {str(e)}')
        return redirect(url_for('cart'))


# ---------------- Аутентификация ----------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Пароли не совпадают')
            return redirect(url_for('register'))

        if User.query.filter_by(username=username).first():
            flash('Имя пользователя уже занято')
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash('Email уже зарегистрирован')
            return redirect(url_for('register'))

        user = User(username=username, email=email)
        user.set_password(password)

        try:
            db.session.add(user)
            db.session.commit()

            login_user(user)
            flash('Регистрация прошла успешно!')
            return redirect(url_for('index'))

        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при регистрации: {str(e)}')

    cart_count = 0
    if current_user.is_authenticated:
        cart_count = CartItem.query.filter_by(user_id=current_user.id).count()

    return render_template('auth/register.html', cart_count=cart_count)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            flash('Вы успешно вошли в систему')
            return redirect(url_for('admin_panel' if user.is_admin else 'index'))

        flash('Неверное имя пользователя или пароль')

    cart_count = 0
    if current_user.is_authenticated:
        cart_count = CartItem.query.filter_by(user_id=current_user.id).count()

    return render_template('auth/login.html', cart_count=cart_count)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Вы вышли из системы')
    return redirect(url_for('index'))


# ---------------- Профиль пользователя ----------------
@app.route('/profile')
@login_required
def profile():
    tab = request.args.get('tab', 'profile')
    cart_count = CartItem.query.filter_by(user_id=current_user.id).count()

    context = {
        'cart_count': cart_count,
        'active_tab': tab
    }

    if tab == 'profile':
        return render_template('auth/profile.html', **context)

    elif tab == 'orders':
        orders = Order.query.filter_by(user_id=current_user.id).order_by(
            Order.created_at.desc()
        ).all()
        context['orders'] = orders
        return render_template('auth/profile_orders.html', **context)

    elif tab == 'addresses':
        addresses = UserAddress.query.filter_by(user_id=current_user.id).order_by(
            UserAddress.is_default.desc()
        ).all()
        context['addresses'] = addresses
        return render_template('auth/profile_addresses.html', **context)

    elif tab == 'support':
        tickets = SupportTicket.query.filter_by(user_id=current_user.id).order_by(
            SupportTicket.created_at.desc()
        ).all()
        context['tickets'] = tickets
        return render_template('auth/profile_support.html', **context)

    elif tab == 'favorites':
        favorites = Favorite.query.filter_by(user_id=current_user.id).all()
        context['favorites'] = favorites
        return render_template('auth/profile_favorites.html', **context)

    return render_template('auth/profile.html', **context)


@app.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    try:
        current_user.first_name = request.form.get('first_name', '')
        current_user.last_name = request.form.get('last_name', '')
        current_user.middle_name = request.form.get('middle_name', '')
        current_user.phone = request.form.get('phone', '')

        birth_date_str = request.form.get('birth_date', '')
        if birth_date_str:
            current_user.birth_date = datetime.strptime(birth_date_str, '%Y-%m-%d').date()

        db.session.commit()
        flash('Профиль успешно обновлен')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при обновлении профиля: {str(e)}')

    return redirect(url_for('profile', tab='profile'))


@app.route('/profile/address/save', methods=['POST'])
@login_required
def save_address():
    try:
        address_id = request.form.get('address_id')

        if address_id:
            address = UserAddress.query.filter_by(id=address_id, user_id=current_user.id).first()
            if not address:
                flash('Адрес не найден')
                return redirect(url_for('profile', tab='addresses'))
        else:
            address = UserAddress(user_id=current_user.id)

        address.title = request.form.get('title', 'Дом')
        address.full_name = request.form.get('full_name', '')
        address.phone = request.form.get('phone', '')
        address.country = request.form.get('country', 'Россия')
        address.city = request.form.get('city', '')
        address.street = request.form.get('street', '')
        address.house = request.form.get('house', '')
        address.apartment = request.form.get('apartment', '')
        address.postal_code = request.form.get('postal_code', '')

        is_default = request.form.get('is_default') == 'on'
        if is_default:
            UserAddress.query.filter_by(user_id=current_user.id).update({'is_default': False})
            address.is_default = True
        elif not UserAddress.query.filter_by(user_id=current_user.id, is_default=True).first():
            address.is_default = True

        latitude = request.form.get('latitude')
        longitude = request.form.get('longitude')
        if latitude and longitude:
            address.latitude = float(latitude)
            address.longitude = float(longitude)

        if not address_id:
            db.session.add(address)

        db.session.commit()
        flash('Адрес успешно сохранен')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при сохранении адреса: {str(e)}')

    return redirect(url_for('profile', tab='addresses'))


@app.route('/profile/address/delete/<int:address_id>')
@login_required
def delete_address(address_id):
    try:
        address = UserAddress.query.filter_by(id=address_id, user_id=current_user.id).first()
        if address:
            db.session.delete(address)
            db.session.commit()
            flash('Адрес удален')
        else:
            flash('Адрес не найден')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при удалении адреса: {str(e)}')

    return redirect(url_for('profile', tab='addresses'))


@app.route('/profile/support/create', methods=['POST'])
@login_required
def create_support_ticket():
    try:
        subject = request.form.get('subject', '')
        message = request.form.get('message', '')
        ticket_type = request.form.get('ticket_type', 'suggestion')

        if not subject or not message:
            flash('Заполните все обязательные поля')
            return redirect(url_for('profile', tab='support'))

        ticket = SupportTicket(
            user_id=current_user.id,
            ticket_number=generate_ticket_number(),
            subject=subject,
            message=message,
            ticket_type=ticket_type
        )

        db.session.add(ticket)
        db.session.commit()
        flash(f'Обращение создано. Номер: {ticket.ticket_number}')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при создании обращения: {str(e)}')

    return redirect(url_for('profile', tab='support'))


# ---------------- Админ-панель ----------------
@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin:
        flash('Доступ запрещен')
        return redirect(url_for('index'))

    products = Product.query.all()
    cart_count = CartItem.query.filter_by(user_id=current_user.id).count()

    return render_template('admin/admin.html',
                           products=products,
                           cart_count=cart_count)


@app.route('/admin/add_product', methods=['GET', 'POST'])
@login_required
def add_product():
    if not current_user.is_admin:
        flash('Доступ запрещен')
        return redirect(url_for('index'))

    if request.method == 'POST':
        try:
            name = request.form['name']
            description = request.form['description']
            price = float(request.form['price'])
            category = request.form['category']
            available_sizes = ','.join(request.form.getlist('sizes'))
            color = request.form['color']
            material = request.form['material']
            brand = request.form['brand']
            main_image = request.form['main_image']
            image2 = request.form.get('image2', '')
            image3 = request.form.get('image3', '')
            available = 'available' in request.form

            product = Product(
                name=name,
                description=description,
                price=price,
                category=category,
                available_sizes=available_sizes,
                color=color,
                material=material,
                brand=brand,
                main_image=main_image,
                image2=image2,
                image3=image3,
                available=available
            )

            db.session.add(product)
            db.session.commit()

            flash('Товар успешно добавлен')
            return redirect(url_for('admin_panel'))

        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при добавлении товара: {str(e)}')

    categories = ['sneakers', 'boots', 'casual', 'sports', 'formal']
    sizes = ['35', '36', '37', '38', '39', '40', '41', '42', '43', '44', '45', '46']
    cart_count = CartItem.query.filter_by(user_id=current_user.id).count()

    return render_template('admin/add_product.html',
                           categories=categories,
                           sizes=sizes,
                           cart_count=cart_count)


@app.route('/admin/edit_product/<int:product_id>', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    if not current_user.is_admin:
        flash('Доступ запрещен')
        return redirect(url_for('index'))

    product = Product.query.get_or_404(product_id)

    if request.method == 'POST':
        try:
            product.name = request.form['name']
            product.description = request.form['description']
            product.price = float(request.form['price'])
            product.category = request.form['category']
            product.available_sizes = ','.join(request.form.getlist('sizes'))
            product.color = request.form['color']
            product.material = request.form['material']
            product.brand = request.form['brand']
            product.main_image = request.form['main_image']
            product.image2 = request.form.get('image2', '')
            product.image3 = request.form.get('image3', '')
            product.available = 'available' in request.form

            db.session.commit()

            flash('Товар успешно обновлен')
            return redirect(url_for('admin_panel'))

        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при обновлении товара: {str(e)}')

    categories = ['sneakers', 'boots', 'casual', 'sports', 'formal']
    all_sizes = ['35', '36', '37', '38', '39', '40', '41', '42', '43', '44', '45', '46']
    selected_sizes = product.available_sizes.split(',') if product.available_sizes else []
    cart_count = CartItem.query.filter_by(user_id=current_user.id).count()

    return render_template('admin/edit_product.html',
                           product=product,
                           categories=categories,
                           sizes=all_sizes,
                           selected_sizes=selected_sizes,
                           cart_count=cart_count)


@app.route('/admin/delete_product/<int:product_id>')
@login_required
def delete_product(product_id):
    if not current_user.is_admin:
        flash('Доступ запрещен')
        return redirect(url_for('index'))

    try:
        product = Product.query.get_or_404(product_id)

        # Если товар уже есть в оформленных заказах — не даём удалить
        from database import OrderItem, Favorite, Review  # если выше уже импортированы, эту строку можно убрать
        has_orders = OrderItem.query.filter_by(product_id=product.id).first()
        if has_orders:
            flash('Нельзя удалить товар, так как он уже есть в оформленных заказах. '
                  'Снимите его с продажи (снимите галочку "Товар в наличии").')
            return redirect(url_for('admin_panel'))

        # Удаляем все связанные записи, которые ссылаются на товар
        CartItem.query.filter_by(product_id=product.id).delete()   # из корзины
        Favorite.query.filter_by(product_id=product.id).delete()   # из избранного
        Review.query.filter_by(product_id=product.id).delete()     # отзывы

        # Теперь можно безопасно удалить сам товар
        db.session.delete(product)
        db.session.commit()
        flash('Товар удален')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при удалении товара: {str(e)}')

    return redirect(url_for('admin_panel'))


# ----- Админ: управление заказами -----
@app.route('/admin/orders')
@login_required
def admin_orders():
    if not current_user.is_admin:
        flash('Доступ запрещен')
        return redirect(url_for('index'))

    status = request.args.get('status', 'all')
    query = Order.query.order_by(Order.created_at.desc())
    if status != 'all':
        query = query.filter_by(status=status)

    orders = query.all()
    cart_count = CartItem.query.filter_by(user_id=current_user.id).count()

    return render_template(
        'admin/orders.html',
        orders=orders,
        status=status,
        cart_count=cart_count
    )


@app.route('/admin/orders/<int:order_id>')
@login_required
def admin_order_detail(order_id):
    if not current_user.is_admin:
        flash('Доступ запрещен')
        return redirect(url_for('index'))

    order = Order.query.get_or_404(order_id)
    cart_count = CartItem.query.filter_by(user_id=current_user.id).count()

    return render_template(
        'admin/order_detail.html',
        order=order,
        cart_count=cart_count
    )


@app.route('/admin/orders/<int:order_id>/status', methods=['POST'])
@login_required
def admin_change_order_status(order_id):
    if not current_user.is_admin:
        flash('Доступ запрещен')
        return redirect(url_for('index'))

    status = request.form.get('status')
    if status not in ['pending', 'processing', 'shipped', 'delivered', 'cancelled']:
        flash('Некорректный статус')
        return redirect(url_for('admin_order_detail', order_id=order_id))

    try:
        order = Order.query.get_or_404(order_id)
        order.status = status
        order.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Статус заказа обновлен')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при обновлении статуса: {e}')

    return redirect(url_for('admin_order_detail', order_id=order_id))


# ----- Админ: поддержка -----
@app.route('/admin/support')
@login_required
def admin_support():
    if not current_user.is_admin:
        flash('Доступ запрещен')
        return redirect(url_for('index'))

    status = request.args.get('status', 'all')
    query = SupportTicket.query.order_by(SupportTicket.created_at.desc())

    if status != 'all':
        query = query.filter_by(status=status)

    tickets = query.all()
    cart_count = CartItem.query.filter_by(user_id=current_user.id).count()

    return render_template('admin/support.html',
                           tickets=tickets,
                           status=status,
                           cart_count=cart_count)


@app.route('/admin/support/respond/<int:ticket_id>', methods=['POST'])
@login_required
def respond_to_ticket(ticket_id):
    if not current_user.is_admin:
        flash('Доступ запрещен')
        return redirect(url_for('index'))

    try:
        ticket = SupportTicket.query.get_or_404(ticket_id)
        ticket.admin_response = request.form.get('admin_response', '')
        ticket.status = request.form.get('status', ticket.status)
        ticket.updated_at = datetime.utcnow()

        db.session.commit()
        flash('Ответ сохранен')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при сохранении ответа: {str(e)}')

    return redirect(url_for('admin_ticket_detail', ticket_id=ticket_id))


@app.route('/admin/support/status/<int:ticket_id>/<status>')
@login_required
def change_ticket_status(ticket_id, status):
    if not current_user.is_admin:
        flash('Доступ запрещен')
        return redirect(url_for('index'))

    try:
        ticket = SupportTicket.query.get_or_404(ticket_id)
        ticket.status = status
        ticket.updated_at = datetime.utcnow()

        db.session.commit()
        flash(f'Статус изменен на {status}')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при изменении статуса: {str(e)}')

    return redirect(url_for('admin_support'))


@app.route('/admin/support/<int:ticket_id>')
@login_required
def admin_ticket_detail(ticket_id):
    if not current_user.is_admin:
        flash('Доступ запрещен')
        return redirect(url_for('index'))

    ticket = SupportTicket.query.get_or_404(ticket_id)
    cart_count = CartItem.query.filter_by(user_id=current_user.id).count()

    return render_template('admin/ticket_detail.html',
                           ticket=ticket,
                           cart_count=cart_count)

@app.route('/add_test_products', methods=['POST'])
@login_required
def add_test_products():
    if not current_user.is_admin:
        flash('Доступ запрещен')
        return redirect(url_for('index'))

    try:
        test_products = [
            Product(
                name='Nike Air Max 270',
                description='Современные кроссовки с максимальным комфортом и технологией Air',
                price=129.99,
                category='sneakers',
                available_sizes='36,37,38,39,40,41,42,43,44',
                color='Черный/Белый',
                material='Текстиль/Синтетика',
                brand='Nike',
                main_image='https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=600&h=400&fit=crop',
                image2='https://images.unsplash.com/photo-1600185365483-26d7a4cc7519?w=600&h=400&fit=crop',
                image3='https://images.unsplash.com/photo-1606107557195-0e29a4b5b4aa?w=600&h=400&fit=crop',
                available=True
            ),
            Product(
                name='Timberland Premium Boots',
                description='Классические ботинки премиум качества, водонепроницаемые',
                price=199.99,
                category='boots',
                available_sizes='40,41,42,43,44,45',
                color='Желтый',
                material='Натуральная кожа',
                brand='Timberland',
                main_image='https://images.unsplash.com/photo-1543163521-1bf539c55dd2?w=600&h=400&fit=crop',
                image2='https://images.unsplash.com/photo-1560769629-975ec94e6a86?w=600&h=400&fit=crop',
                image3='https://images.unsplash.com/photo-1525966222134-fcfa99b8ae77?w=600&h=400&fit=crop',
                available=True
            ),
            Product(
                name='Adidas Ultraboost 22',
                description='Беговые кроссовки с технологией Boost для максимальной амортизации',
                price=149.99,
                category='sports',
                available_sizes='37,38,39,40,41,42,43',
                color='Синий',
                material='Текстиль',
                brand='Adidas',
                main_image='https://images.unsplash.com/photo-1600185365483-26d7a4cc7519?w=600&h=400&fit=crop',
                image2='https://images.unsplash.com/photo-1606107557195-0e29a4b5b4aa?w=600&h=400&fit=crop',
                image3='https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=600&h=400&fit=crop',
                available=True
            )
        ]

        for product in test_products:
            db.session.add(product)

        db.session.commit()
        flash('Тестовые товары успешно добавлены!')

    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при добавлении тестовых товаров: {str(e)}')

    return redirect(url_for('index'))

@app.route('/accept_cookies', methods=['POST'])
def accept_cookies():
    resp = make_response(redirect(request.referrer or url_for('index')))
    resp.set_cookie('cookie_accepted', '1', max_age=60 * 60 * 24 * 365)  # 1 год
    return resp

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
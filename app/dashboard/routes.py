from flask import render_template, session, redirect, url_for, request, flash
from app.dashboard import dashboard
from app import mysql
from datetime import datetime
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import io
import base64

@dashboard.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
        
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM transactions WHERE user_id=%s", (session['user_id'],))
    rows = cur.fetchall()
    cur.close()

    if rows:
        columns = ['id', 'user_id', 'txn_date', 'description', 'ref_num', 'debit', 'credit', 'balance', 'category', 'created_at']
        df = pd.DataFrame(rows, columns=columns)
        
        # Numbers ko float mein badalna
        df['debit'] = df['debit'].astype(float)
        df['credit'] = df['credit'].astype(float)

        # Dashboard ke main metrics calculate karna
        total_spent = round(df['debit'].sum())
        total_transactions = len(df)
        total_savings = round(df['credit'].sum() - df['debit'].sum())
        top_category = df.groupby('category')['debit'].sum().idxmax()

        # Data ko dictionary list mein badalna
        all_txns = df.to_dict(orient='records')
        
        # Date ke hisab se latest 5 transactions nikalna
        recent_txns = sorted(all_txns, key=lambda x: str(x['txn_date']), reverse=True)[:5]
        
    else:
        # Agar table khali ho
        total_spent = 0
        total_transactions = 0
        total_savings = 0
        top_category = 'N/A'
        recent_txns = []

    # YAHAN DHYAN DENA: Yeh variable names exactly dashboard.html se match hone chahiye!
    return render_template('dashboard.html',
                           total_spent=total_spent,
                           total_transactions=total_transactions,
                           total_savings=total_savings,
                           top_category=top_category,
                           recent_transactions=recent_txns)

@dashboard.route('/add-expense', methods=['GET', 'POST'])
def add_expense():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        txn_date = request.form['txn_date']
        description = request.form['description']
        category = request.form['category']
        debit = request.form['debit'] or 0
        credit = request.form['credit'] or 0

        cur = mysql.connection.cursor()
        cur.execute("""INSERT INTO transactions 
                    (user_id, txn_date, description, category, debit, credit) 
                    VALUES (%s, %s, %s, %s, %s, %s)""",
                    (session['user_id'], txn_date, description, category, debit, credit))
        mysql.connection.commit()
        cur.close()

        flash('Expense added successfully!', 'success')
        return redirect(url_for('dashboard.transactions'))

    return render_template('add_expense.html')

@dashboard.route('/transactions')
def transactions():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    search = request.args.get('search', '')
    category = request.args.get('category', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    min_amount = request.args.get('min_amount', '')
    max_amount = request.args.get('max_amount', '')

    query = "SELECT * FROM transactions WHERE user_id = %s"
    params = [session['user_id']]

    if search:
        query += " AND description LIKE %s"
        params.append(f'%{search}%')

    if category:
        query += " AND category = %s"
        params.append(category)

    if date_from:
        query += " AND txn_date >= %s"
        params.append(date_from)

    if date_to:
        query += " AND txn_date <= %s"
        params.append(date_to)

    if min_amount:
        query += " AND debit >= %s"
        params.append(min_amount)

    if max_amount:
        query += " AND debit <= %s"
        params.append(max_amount)

    query += " ORDER BY txn_date DESC"

    cur = mysql.connection.cursor()
    cur.execute(query, params)
    transactions = cur.fetchall()
    cur.close()

    return render_template('transactions.html', transactions=transactions)

@dashboard.route('/edit-expense/<int:txn_id>', methods=['GET', 'POST'])
def edit_expense(txn_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor()

    if request.method == 'POST':
        txn_date = request.form['txn_date']
        description = request.form['description']
        category = request.form['category']
        debit = request.form['debit'] or 0
        credit = request.form['credit'] or 0

        cur.execute("""UPDATE transactions
                        SET txn_date=%s, description=%s, category=%s, debit=%s, credit=%s
                        WHERE id=%s AND user_id=%s""",
                     (txn_date, description, category, debit, credit, txn_id, session['user_id']))
        mysql.connection.commit()
        cur.close()

        flash('Expense updated successfully!', 'success')
        return redirect(url_for('dashboard.transactions'))

    cur.execute("SELECT * FROM transactions WHERE id=%s AND user_id=%s",
                 (txn_id, session['user_id']))
    txn = cur.fetchone()
    cur.close()

    if txn is None:
        flash('Transaction not found!', 'danger')
        return redirect(url_for('dashboard.transactions'))

    return render_template('edit_expense.html', txn=txn)


@dashboard.route('/delete-expense/<int:txn_id>')
def delete_expense(txn_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM transactions WHERE id=%s AND user_id=%s",
                 (txn_id, session['user_id']))
    mysql.connection.commit()
    cur.close()

    flash('Expense deleted successfully!', 'success')
    return redirect(url_for('dashboard.transactions'))

@dashboard.route('/upload-csv', methods=['GET', 'POST'])
def upload_csv():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        file = request.files['csv_file']

        if not file or file.filename == '':
            flash('No file selected!', 'danger')
            return redirect(url_for('dashboard.upload_csv'))

        df = pd.read_csv(file)

        # Category keyword mapping
        category_map = {
        # Investment - rakha gaya transfer se PEHLE taaki match order sahi rahe
        'sip': 'Investment',
        'mutual fund': 'Investment',
        'zerodha': 'Investment',
        'groww': 'Investment',
        'upstox': 'Investment',
        'angel one': 'Investment',
        'ppf': 'Investment',
        'nps': 'Investment',
        'fd': 'Investment',
        'fixed deposit': 'Investment',
        'rd': 'Investment',
        'recurring deposit': 'Investment',
        'dividend': 'Investment',

        # Food & Dining
        'swiggy': 'Food & Dining',
        'zomato': 'Food & Dining',
        'restaurant': 'Food & Dining',
        'cafe': 'Food & Dining',
        'dhaba': 'Food & Dining',
        'hotel': 'Food & Dining',
        'dominos': 'Food & Dining',
        'mcdonald': 'Food & Dining',
        'kfc': 'Food & Dining',

        # Transport
        'uber': 'Transport',
        'ola': 'Transport',
        'rapido': 'Transport',
        'petrol': 'Transport',
        'fuel': 'Transport',
        'metro': 'Transport',
        'irctc': 'Transport',
        'fastag': 'Transport',
        'cab': 'Transport',

        # Shopping
        'amazon': 'Shopping',
        'flipkart': 'Shopping',
        'myntra': 'Shopping',
        'ajio': 'Shopping',
        'meesho': 'Shopping',
        'shein': 'Shopping',
        'mall': 'Shopping',

        # Utilities
        'electricity': 'Utilities',
        'recharge': 'Utilities',
        'water bill': 'Utilities',
        'gas': 'Utilities',
        'broadband': 'Utilities',
        'wifi': 'Utilities',
        'dth': 'Utilities',

        # Healthcare
        'hospital': 'Healthcare',
        'pharmacy': 'Healthcare',
        'medicine': 'Healthcare',
        'doctor': 'Healthcare',
        'clinic': 'Healthcare',
        'apollo': 'Healthcare',
        'medplus': 'Healthcare',

        # Transfer
        'transfer': 'Transfer',
        'upi': 'Transfer',
        'neft': 'Transfer',
        'imps': 'Transfer',
        'rtgs': 'Transfer',

        # Entertainment
        'netflix': 'Entertainment',
        'prime video': 'Entertainment',
        'hotstar': 'Entertainment',
        'spotify': 'Entertainment',
        'bookmyshow': 'Entertainment',
        'pvr': 'Entertainment',
        'inox': 'Entertainment',
}

        def categorize(description):
            desc = str(description).lower()
            for keyword, category in category_map.items():
                if keyword in desc:
                    return category
            return 'Other'

        cur = mysql.connection.cursor()

        for _, row in df.iterrows():
                txn_date = row.get('Txn Date')
                txn_date = pd.to_datetime(txn_date, format='mixed', dayfirst=True).strftime('%Y-%m-%d')
                description = row.get('Description')
                ref_number = row.get('Ref No./Cheque No.')
                debit = row.get('Debit')
                credit = row.get('Credit')
                balance = row.get('Balance')

                debit = 0 if pd.isna(debit) else debit
                credit = 0 if pd.isna(credit) else credit
                ref_number = '' if pd.isna(ref_number) else ref_number

                category = categorize(description)

                cur.execute("""INSERT INTO transactions
                                (user_id, txn_date, description, ref_number, debit, credit, balance, category)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                            (session['user_id'], txn_date, description, ref_number, debit, credit, balance, category))

        mysql.connection.commit()
        cur.close()

        flash(f'{len(df)} transactions imported successfully!', 'success')
        return redirect(url_for('dashboard.transactions'))

    return render_template('upload_csv.html')

@dashboard.route('/analytics')
def analytics():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM transactions WHERE user_id=%s", (session['user_id'],))
    rows = cur.fetchall()
    cur.close()

    columns = ['id', 'user_id', 'txn_date', 'description', 'ref_number',
               'debit', 'credit', 'balance', 'category', 'created_at']
    df = pd.DataFrame(rows, columns=columns)

    # Empty state check - agar koi transaction nahi hai
    if df.empty:
        return render_template('analytics.html', has_data=False)

    # --- Pehle aapka normal conversion code ---
    df['txn_date'] = pd.to_datetime(df['txn_date'])
    df['debit'] = df['debit'].astype(float)
    df['credit'] = df['credit'].astype(float)
# 1. Parameter fetch karo aur check karo backend mein kya aa raha hai
    current_year = datetime.now().year
    selected_months = request.args.getlist('months')
    selected_year = request.args.get('selected_year', str(current_year))  # <-- Yeh line add karo
    
    print("--- DEBUG: Selected Months from URL ---", selected_months)
    print("--- DEBUG: Selected Year from URL ---", selected_year)   # <-- Yeh line add karo

    df['year_month_str'] = df['txn_date'].dt.strftime('%Y-%m')
    # Data ke saare unique saal nikal kar list banao
    available_years = sorted(df['txn_date'].dt.year.unique().tolist(), reverse=True)
# # --- MONTH FILTER SE PEHLE YEH COPIED LF WAALA HISSA LAGANA HAI
    if selected_year and selected_year != '':
        df = df[df['txn_date'].dt.year == int(selected_year)]  # <-- Is line ke aage 4 spaces (ya ek Tab) de do

    # Iske niche aapka mushkil se sahi kiya hua month filter jaisa hai waisa hi chalega:
    if 'All' not in selected_months and len(selected_months) > 0:
        pass
    # Aapka purana logic...
    print("--- DEBUG: DataFrame Months Available ---", df['year_month_str'].unique())

    # 2. Default state check
    if not selected_months:
        pass

    # 3. Filtering logic
    if 'All' not in selected_months and len(selected_months) > 0:
        available_months_in_df = df['year_month_str'].unique()
        missing_months = [m for m in selected_months if m not in available_months_in_df]
        
        filtered_df = df[df['year_month_str'].isin(selected_months)].copy()
        print("--- DEBUG: Filtered DF Shape ---", filtered_df.shape)

        if missing_months:
            flash("No data found for the selected filter. Showing all available data instead.", "warning")

        if not filtered_df.empty:
            df = filtered_df
        # 4. Amount filter logic
    min_amount = request.args.get('min_amount', 0, type=int)
    if min_amount > 0:
        filtered_by_amount = df[df['debit'] >= min_amount].copy()
        if not filtered_by_amount.empty:
            df = filtered_by_amount
        else:
            flash(f"No transactions found above ₹{min_amount}. Showing all available data instead.", "warning")
    # ==================================================
    # 2. MONTHLY SPENDING CALCULATION (Is line ko yahan hona chahiye)
    # ==================================================
    df['month'] = df['txn_date'].dt.to_period('M')
    monthly_spending = df.groupby('month')['debit'].sum()

    # 3. Category-wise breakdown
    category_breakdown = df.groupby('category')['debit'].sum()

    # 4. Average monthly spend logic (Safe check with empty check)
    if not monthly_spending.empty:
        avg_monthly_spend = monthly_spending.mean()
    else:
        avg_monthly_spend = 0.0

    # 5. Total savings vs expenditure
    total_credit = df['credit'].sum()
    total_debit = df['debit'].sum()
    savings = total_credit - total_debit

    # 6. Unusual spike detection
    spikes = df[df['debit'] > 2 * avg_monthly_spend]
    # Chart 1: Horizontal Bar chart - Monthly spending trends
    import matplotlib.ticker as ticker
    fig1, ax1 = plt.subplots(figsize=(7, 6))
    short_month_names = [m.strftime('%b') for m in monthly_spending.index]
    ax1.barh(short_month_names, monthly_spending.values, color="#4361ee", edgecolor='white', height=0.6)
    if len(short_month_names) == 1:
        ax1.set_ylim(-1, 1)
    ax1.set_title('Monthly Spending Trend', fontsize=24, fontweight='bold', color='#2c3e50', pad=15)
    ax1.set_xlabel('Total Debit (₹)', fontsize=20)
    ax1.set_ylabel('Month', fontsize=20)
    ax1.tick_params(axis='both', which='major', labelsize=18)
    def format_rupees(x, pos):
        if x >= 10000000:   # 1 Crore ya usse zyada (10,00,00,000 -> 10Cr)
            return f'₹{x*1e-7:.0f}Cr'
        elif x >= 100000:   # 1 Lakh ya usse zyada (10,00,000 -> 10L)
            return f'₹{x*1e-5:.0f}L'
        elif x >= 1000:     # Thousands (50,000 -> 50K)
            return f'₹{x*1e-3:.0f}K'
        return f'₹{int(x)}' # Normal small numbers ke liye

    # Is format rule ko X-axis par apply kar do
    ax1.xaxis.set_major_formatter(ticker.FuncFormatter(format_rupees))
    ax1.set_facecolor('#f8f9fa')
    fig1.patch.set_facecolor('#ffffff')
    plt.tight_layout()
    chart1 = fig_to_base64(fig1)

    # ---------------------------------------------------------
    # Chart 2: Category breakdown - Converted to Vertical Bar Chart
    # ---------------------------------------------------------
    fig2, ax2 = plt.subplots(figsize=(6, 5.5))
    cat_data = category_breakdown[category_breakdown > 0]
    # 'Other' ko hamesha last mein rakhne ke liye reorder karo
    if 'Other' in cat_data.index:
        other_value = cat_data['Other']
        cat_data = cat_data.drop('Other')
        cat_data['Other'] = other_value
    ax2.bar(cat_data.index, cat_data.values, color='#f72585', edgecolor='white')
    if len(cat_data) == 1:
        ax2.set_xlim(-2, 2)
    ax2.set_yticks(range(0, int(cat_data.max()) + 25000, 25000))  
    ax2.set_title('Category-wise Spending', fontsize=18, fontweight='bold', color='#2c3e50', pad=15)
    ax2.set_xlabel('Category', fontsize=20)
    ax2.set_ylabel('Debit (₹)', fontsize=20)
    plt.xticks(rotation=45, ha='right', fontsize=12)
    plt.yticks(fontsize=12)

    ax2.set_facecolor('#f8f9fa')
    fig2.patch.set_facecolor('#ffffff')
    plt.tight_layout()
    chart2 = fig_to_base64(fig2)

    daily_spending = df.groupby('txn_date')['debit'].sum()
    # Chart 3: Line chart - Spending over time
    fig3, ax3 = plt.subplots(figsize=(8, 5))
    daily_spending.plot(kind='line', ax=ax3, marker='o', color="#0633C5", linewidth=2, markersize=5, markerfacecolor='white', markeredgewidth=2)
    ax3.set_title('Spending Over Time', fontsize=17, fontweight='bold', color='#2c3e50', pad=15)
    selected_year = request.args.get('selected_year', '2026')
    ax3.set_xlabel(f'Date ({selected_year})', fontsize=16)
    ax3.set_ylabel('Debit (₹)', fontsize=16)
    ax3.set_facecolor('#f8f9fa')
    fig3.patch.set_facecolor('#ffffff')
    import matplotlib.dates as mdates
    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%d %b'))
    plt.xticks(rotation=0, fontsize=11)
    plt.yticks(fontsize=11)
    plt.tight_layout()
    chart3 = fig_to_base64(fig3)

# ---------------------------------------------------------
    # Chart 4: Cash Flow (Total Credit vs Total Debit) - Exploded Pie Chart
    fig4, ax4 = plt.subplots(figsize=(5,4))
    labels = ['Income', 'Expense']
    sizes = [total_credit, total_debit]
    colors = ["#4361ee", "#f72585"]
    explode = (0.05, 0.05)
    
    ax4.pie(sizes, explode=explode, labels=labels, colors=colors,
            autopct='%1.1f%%', shadow=True, startangle=140,
            textprops={'fontsize': 12, 'fontweight': 'bold'})
    
    ax4.set_title('Cash Flow (Income vs.Expense)', fontsize=18, fontweight='bold', color='#2c3e50', pad=15)
    fig4.patch.set_facecolor('#ffffff')
    plt.tight_layout()
    fig4.subplots_adjust(bottom=0.06)
    chart4 = fig_to_base64(fig4)

    return render_template('analytics.html',
                            selected_months=selected_months,
                            avg_monthly_spend=round(avg_monthly_spend, 2),
                            total_credit=total_credit,
                            total_debit=total_debit,
                            savings=savings,
                            chart1=chart1,
                            chart2=chart2,
                            chart3=chart3,
                            chart4=chart4,
                            available_years=available_years,
                            selected_year=selected_year,
                            spikes=spikes)

def fig_to_base64(fig):
    img = io.BytesIO()
    fig.savefig(img, format='png', bbox_inches='tight')
    img.seek(0)
    plot_url = base64.b64encode(img.getvalue()).decode('utf-8')
    plt.close(fig)
    return plot_url
import pyodbc

SERVER   = 'DESKTOP-U3IB29K\\SQLEXPRESS'
DATABASE = 'JJJW_DB'

def get_connection():
    return pyodbc.connect(
        f'DRIVER={{ODBC Driver 17 for SQL Server}};'
        f'SERVER={SERVER};'
        f'DATABASE={DATABASE};'
        f'Trusted_Connection=yes;'
    )
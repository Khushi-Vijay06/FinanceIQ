import sys
sys.path.insert(0, '.')

from app import app

print(app.url_map)

if __name__ == '__main__':
    app.run(debug=True)
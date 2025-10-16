# Тест всех реализованных команд
echo "=== Тест VFS ==="
ls
cd project
ls
cd docs
ls
cd api
ls
tac index.html
cd ../..
cd src
ls
cd core
tac main.py

echo "=== Тест команд history/touch ==="
touch new_file.txt
ls
history

echo "=== Проверка ошибок ==="
cd nowhere
tac notexists.txt
foobar

# Тест VFS с 3+ уровнями вложенности
echo "=== Тест глубокой структуры ==="
ls
cd project
ls
cd src/core
ls
cd ../..
ls tests
cd ../../..
ls
pwd
exit
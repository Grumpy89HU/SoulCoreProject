#!/bin/bash
GREEN='\033[0;32m'
NC='\033[0m'

source ~/magyardataset/bin/activate

while true; do
    echo -e "${GREEN}--- LÉLEK CORE INDÍTÁSA ---${NC}"
    python3 main.py
    
    # Ha a Python 0-val áll le (Stop), akkor kilépünk a hurokból
    if [ $? -eq 0 ]; then
        echo "Leállítás nyugtázva."
        break
    fi
    
    echo "Restart vagy hiba történt. Újraindítás..."
    sleep 2
done

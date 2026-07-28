"""Script para reorganizar os arquivos do NEXUS para dentro da subpasta Projetos/NEXUS.
"""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Lista de itens a serem movidos para Projetos/NEXUS
ITEMS = [
    "app",
    "scripts",
    "frontend",
    "tests",
    "paper",
    "dados_amostra",
    "out",
    "requirements.txt",
    "README.md",
    "COMO_RODAR.md",
    "REPERTORIO.md",
    "COMO_INCLUIR_DADOS_AMOSTRA_GITHUB.md",
    "PASSO_A_PASSO_SUBIR_GITHUB.md",
    "verificar_seguranca_github.bat",
    "configurar_ambiente_seguro.bat",
]

TARGET_DIR = ROOT / "Projetos" / "NEXUS"

def mover_arquivos():
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    
    for item_name in ITEMS:
        src = ROOT / item_name
        if src.exists() and src != (ROOT / "scripts"): # Não mover o script atual enquanto executa
            dest = TARGET_DIR / item_name
            if src.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.move(str(src), str(dest))
            else:
                shutil.move(str(src), str(dest))
            print(f"[MOVIDO] {item_name} -> Projetos/NEXUS/{item_name}")

    # Move a pasta scripts por último
    src_scripts = ROOT / "scripts"
    if src_scripts.exists():
        dest_scripts = TARGET_DIR / "scripts"
        if dest_scripts.exists():
            shutil.rmtree(dest_scripts)
        shutil.move(str(src_scripts), str(dest_scripts))
        print("[MOVIDO] scripts -> Projetos/NEXUS/scripts")

    print("\n============================================================")
    print("  ESTRUTURA ORGANIZADA EM 'Projetos/NEXUS/' COM SUCESSO!")
    print("============================================================")

if __name__ == "__main__":
    mover_arquivos()

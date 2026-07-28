from flask import Flask, request, jsonify
from pymongo import MongoClient
from datetime import datetime

app = Flask(__name__)

# --- CONEXÃO COM O MONGODB ---
client = MongoClient("mongodb://mongo_db")
db = client["seu banco"]            # nome do banco
colecao = db["colecao"]         # coleção

# --- ROTA PRINCIPAL ---
@app.route("/", methods=["GET"])
def home():
    return "Servidor da API está ON — envie dados via POST para /api/colecao"

# --- ROTA PARA RECEBER OS DADOS DOS SENSORES ---
@app.route("/api/colecao", methods=["POST"])
def salvar_dados():
    try:
        dados = request.get_json()

        # Verifica se o JSON contém os campos esperados
        campos_esperados = ["temperatura", "umidade_ar", "umidade_solo"]
        for campo in campos_esperados:
            if campo not in dados:
                return jsonify({"erro": f"Campo '{campo}' ausente no JSON"}), 400

        # Adiciona data e hora automática
        dados["dataRegistro"] = datetime.now()

        # Salva no MongoDB
        resultado = colecao.insert_one(dados)

        # Remove o _id gerado pelo MongoDB (não é serializável)
        dados.pop("_id", None)

        # Converte a data para string
        dados["dataRegistro"] = dados["dataRegistro"].strftime("%Y-%m-%d %H:%M:%S")

        return jsonify({
            "mensagem": "Dados recebidos e armazenados com sucesso!",
            "id": str(resultado.inserted_id),
            "dados": dados
        }), 201

    except Exception as e:
        return jsonify({"erro": str(e)}), 400


# --- INICIAR SERVIDOR ---
if __name__ == "__main__":
    app.run(host="192.168.1.103", port=8080, debug=True)
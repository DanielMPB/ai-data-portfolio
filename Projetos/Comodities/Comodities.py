import csv

dados_paises = {}
def carregar_dados_do_csv(value_of_imports): #Busca dados arquivo
    with open(value_of_imports, encoding='utf-8') as arquivo:
        leitor = csv.reader(arquivo)
        cabecalho = next(leitor)

        for linha in leitor:
            pais = linha[5]
            commodity = linha[7]
            try:
                valor = float(linha[-1])
            except ValueError:
                continue

            if pais not in dados_paises:
                dados_paises[pais] = {
                    "valor_total": 0,
                    "commodities": []
                }

            dados_paises[pais]["valor_total"] += valor
            if commodity not in dados_paises[pais]["commodities"]:
                dados_paises[pais]["commodities"].append(commodity)

    return dados_paises
##############################################################################################
def busca_dado(pais): 
    total = dados_paises[pais]["valor_total"] # tq[0]
    quantidade = len(dados_paises[pais]["commodities"]) #tq[1]
    tq = total, quantidade
    return tq
################################################################################################
def menu():
    while True:
        print("\n--- MENU ---")
        print("1. Ver ranking dos países")
        print("2. Buscar um país")
        print("3. Ver países por commodity")
        print("4. Recomendação")
        print("5. Sair")
        opcao = input("Escolha uma opção (1 a 5): ")

        if opcao == "1":
            exibir_ranking()
        elif opcao == "2":
            nome = input("Digite o nome do país: ")
            buscar_pais( nome)
        elif opcao == "3":
            commodity = input("Digite o nome da commodity e o número Ex:Footwear (85): ")
            listar_paises_por_commodity(commodity)
        elif opcao == "4":
            perfil= definir_perfil()
            recomendar_comodities(perfil)
        elif opcao == "5":
            print("OK, programa sera encerrado ")
            break
        else:
            print("Opção inválida! Tente novamente.")

##################################################################################################

def exibir_ranking(top=10): #opição 1 que mostra o top 10
    ranking = [] #crio  a lista que vai mostrar o rank
    for pais in dados_paises: 
        tq = busca_dado(pais)
        ranking.append((pais,tq[0],tq[1]))

    for i in range(len(ranking)):
        for j in range(i + 1, len(ranking)):
            if ranking[j][1] > ranking[i][1]:
                ranking[i], ranking[j] = ranking[j], ranking[i]

    print(f"Top {top} países por valor total de importações:")
    for i in range(top):
        pais, valor, qtd = ranking[i]
        print(f"{i+1}. {pais} - €{valor:,.2f} mil euros - {qtd} tipos de commodities")
# fim  do codigo do rank#
#####################################################################################################
# opção dois :  buscar paises
def buscar_pais( pais):
    if pais in dados_paises:
        tq = busca_dado(pais)
        print(f"\nDados do país: {pais}")
        print(f"Valor total importado: €{tq[0]:,.2f} mil euros")
        print(f"Tipos de commodities importadas: {tq[1]}")
        print("Lista de commodities:")
        for c in dados_paises[pais]["commodities"]:
            print(f"- {c}")
    else:
        print("País não encontrado.")
 # fim da opção dois       
#######################################################################################################        
# commodity      
def listar_paises_por_commodity(nome_commodity):
    print(f"\nPaíses que importam a commodity '{nome_commodity}':")
    encontrou = False
    for pais in dados_paises:
        if nome_commodity in dados_paises[pais]["commodities"]:
            print(f"- {pais}")
            encontrou = True
    if not encontrou:
        print("Nenhum país encontrado com essa commodity.")
########################################################################################################
def definir_perfil():
    pontos = 0
    r1=  r2 = r3 = 0 
    
    print("\nResponda com 's' para sim e 'n' para não:")
    while r1 != 's'  and r1 != 'n' :
      r1 = input("Você prefere segurança a retorno alto? (s/n): ").lower()
      if r1 == 's':
       pontos += 1
     
    while r2 != 's'  and r2 != 'n' :
     r2 = input("Você aceitaria ver seu investimento oscilar para ganhar mais? (s/n): ").lower()
    
     if r2 == 'n':
        pontos += 1
    
    while r3 != 's'  and r3 !='n' :
     r3 = input("Você prefere diversificar para não perder tudo de uma vez? (s/n): ").lower()
     if r3 == 's':
        pontos += 1
   
 
    # Define o perfil com base na pontuação
    if pontos >= 2:
        perfil = "Conservador"
    elif pontos == 1:
        perfil = "Moderado"
    else:
        perfil = "Ousado"

    print(f"\nSeu perfil de investidor é: {perfil}")
    return perfil
#####################################################################################################
def recomendar_comodities(perfil):
    print("\nRecomendações de commodities para seu perfil:")

    if perfil == "Conservador":
        print("- Ouro")
        print("- Alimentos básicos")
        print("- Energia (petróleo estável)")
    elif perfil == "Moderado":
        print("- Soja")
        print("- Minério de ferro")
        print("- Gás natural")
    elif perfil == "Ousado":
        print("- Petróleo")
        print("- Metais raros")
        print("- Commodities com variação cambial")
################################################################################################################
carregar_dados_do_csv("value_of_imports.csv")
menu()
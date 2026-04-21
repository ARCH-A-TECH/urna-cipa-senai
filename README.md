# Urna Eletrônica — CIPA SENAI

Sistema de votação eletrônica para eleições da CIPA (Comissão Interna de Prevenção de Acidentes) do SENAI.

## Funcionalidades

- Criação de eleições com upload de planilha CSV de funcionários autorizados
- Cadastro de candidatos com foto
- Validação de CPF pela lista de funcionários
- Votação com teclado numérico estilo urna eletrônica
- Dashboard de resultados com gráficos (barras e rosca)
- Relatório de participação (votaram / não votaram)
- Impressão de zerésima, resultado e relatório de participação
- Acessibilidade com modo de alto contraste e leitura por voz

## Senha do mesário

```
cipa2025
```

## Executar localmente

```bash
pip install flask gunicorn
python app.py
```

Acesse: http://localhost:5000

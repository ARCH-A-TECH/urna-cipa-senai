from flask import Flask, render_template, request, jsonify, send_from_directory, session
import json, os, shutil, csv, io, base64, uuid, hashlib
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'cipa_senai_urna_secret_v2_2026'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

ELEICOES_DIR = 'eleicoes'
GLOBAL_CPF_FILE = 'cpfs_globais.json'
MESARIOS_FILE = 'mesarios.json'
os.makedirs(ELEICOES_DIR, exist_ok=True)

# Default admin mesário (only created if file doesn't exist)
DEFAULT_ADMIN_USER = 'admin'
DEFAULT_ADMIN_PASS = 'cipa2025'

# ── Password hashing ─────────────────────────────────────────────────────────

def hash_senha(senha):
    return hashlib.sha256(senha.encode('utf-8')).hexdigest()

# ── Mesário system ───────────────────────────────────────────────────────────

def load_mesarios():
    if os.path.exists(MESARIOS_FILE):
        with open(MESARIOS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    # First run: create default admin with temporary password
    mesarios = {
        DEFAULT_ADMIN_USER: {
            'nome': 'Administrador',
            'senha_hash': hash_senha(DEFAULT_ADMIN_PASS),
            'admin': True,
            'senha_temporaria': True,
            'criado_em': ts()
        }
    }
    save_mesarios(mesarios)
    return mesarios

def save_mesarios(mesarios):
    with open(MESARIOS_FILE, 'w', encoding='utf-8') as f:
        json.dump(mesarios, f, ensure_ascii=False, indent=2)

def autenticar_mesario(usuario, senha):
    """Returns (ok, nome) tuple."""
    mesarios = load_mesarios()
    usuario = usuario.strip().lower()
    if usuario in mesarios:
        if mesarios[usuario]['senha_hash'] == hash_senha(senha):
            return True, mesarios[usuario]['nome']
    return False, None

def is_admin(usuario):
    mesarios = load_mesarios()
    return mesarios.get(usuario, {}).get('admin', False)

def mesario_logado():
    """Returns (usuario, nome) or (None, None)."""
    if 'mesario_usuario' in session and 'mesario_nome' in session:
        return session['mesario_usuario'], session['mesario_nome']
    return None, None

def require_mesario():
    u, n = mesario_logado()
    return u is not None

# ── Election helpers ─────────────────────────────────────────────────────────

def lista_eleicoes():
    return sorted([d for d in os.listdir(ELEICOES_DIR)
                   if os.path.isdir(os.path.join(ELEICOES_DIR, d))])

def data_path(eid): return os.path.join(ELEICOES_DIR, eid, 'dados.json')
def log_path(eid):  return os.path.join(ELEICOES_DIR, eid, 'log.json')
def photos_dir(eid):
    p = os.path.join(ELEICOES_DIR, eid, 'fotos')
    os.makedirs(p, exist_ok=True)
    return p

def load_election(eid):
    p = data_path(eid)
    if os.path.exists(p):
        with open(p, 'r', encoding='utf-8') as f: return json.load(f)
    return None

def save_election(eid, data):
    os.makedirs(os.path.join(ELEICOES_DIR, eid), exist_ok=True)
    with open(data_path(eid), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_log(eid):
    p = log_path(eid)
    if os.path.exists(p):
        with open(p, 'r', encoding='utf-8') as f: return json.load(f)
    return []

def append_log(eid, entry):
    # Auto-enrich log with mesário name if logged in
    if 'mesario' not in entry:
        _, nome = mesario_logado()
        if nome:
            entry['mesario'] = nome
    log = load_log(eid)
    log.append(entry)
    with open(log_path(eid), 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

# ── GLOBAL CPF REGISTRY ──────────────────────────────────────────────────────

def load_global_cpfs():
    if os.path.exists(GLOBAL_CPF_FILE):
        with open(GLOBAL_CPF_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_global_cpfs(data):
    with open(GLOBAL_CPF_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def register_cpf_vote(cpf, eid):
    g = load_global_cpfs()
    g[cpf] = eid
    save_global_cpfs(g)

def cpf_has_voted(cpf):
    g = load_global_cpfs()
    if cpf not in g:
        return None
    eid = g[cpf]
    d = load_election(eid)
    if d is None:
        del g[cpf]
        save_global_cpfs(g)
        return None
    return eid

def release_cpfs_for_election(eid):
    """Remove all CPFs bound to a given election from the global registry."""
    g = load_global_cpfs()
    to_del = [cpf for cpf, e in g.items() if e == eid]
    for cpf in to_del:
        del g[cpf]
    save_global_cpfs(g)

# ── GLOBAL HISTORY (archive of deleted elections) ────────────────────────────

GLOBAL_HISTORY_FILE = 'historico_global.json'

def load_global_history():
    if os.path.exists(GLOBAL_HISTORY_FILE):
        with open(GLOBAL_HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_global_history(data):
    with open(GLOBAL_HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def append_global_history(entry):
    h = load_global_history()
    h.append(entry)
    save_global_history(h)

def ts():
    return datetime.now().strftime('%d/%m/%Y %H:%M:%S')

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/fotos/<eid>/<filename>')
def serve_photo(eid, filename):
    return send_from_directory(photos_dir(eid), filename)

# ─── MESÁRIO AUTH ─────────────────────────────────────────────────────────────

@app.route('/api/mesario/login', methods=['POST'])
def mesario_login():
    dados = request.json
    usuario = dados.get('usuario', '').strip().lower()
    senha = dados.get('senha', '')
    ok, nome = autenticar_mesario(usuario, senha)
    if not ok:
        return jsonify({'ok': False, 'msg': 'Usuário ou senha incorretos.'})
    session['mesario_usuario'] = usuario
    session['mesario_nome'] = nome
    session['mesario_admin'] = is_admin(usuario)
    # Check if password is temporary (first login forces password change)
    mesarios = load_mesarios()
    senha_temporaria = mesarios.get(usuario, {}).get('senha_temporaria', False)
    return jsonify({
        'ok': True,
        'nome': nome,
        'admin': session['mesario_admin'],
        'senha_temporaria': senha_temporaria
    })

@app.route('/api/mesario/logout', methods=['POST'])
def mesario_logout():
    session.pop('mesario_usuario', None)
    session.pop('mesario_nome', None)
    session.pop('mesario_admin', None)
    return jsonify({'ok': True})

@app.route('/api/mesario/me', methods=['GET'])
def mesario_me():
    u, n = mesario_logado()
    if u is None:
        return jsonify({'ok': False})
    mesarios = load_mesarios()
    senha_temporaria = mesarios.get(u, {}).get('senha_temporaria', False)
    return jsonify({
        'ok': True, 'usuario': u, 'nome': n,
        'admin': session.get('mesario_admin', False),
        'senha_temporaria': senha_temporaria
    })

@app.route('/api/mesario/cadastrar', methods=['POST'])
def cadastrar_mesario():
    if not require_mesario():
        return jsonify({'ok': False, 'msg': 'Acesso restrito. Faça login como mesário.'})
    dados = request.json
    usuario = dados.get('usuario', '').strip().lower()
    nome = dados.get('nome', '').strip()
    senha = dados.get('senha', '')
    if not usuario or not nome or not senha:
        return jsonify({'ok': False, 'msg': 'Preencha todos os campos.'})
    if len(senha) < 4:
        return jsonify({'ok': False, 'msg': 'Senha deve ter ao menos 4 caracteres.'})
    if not usuario.replace('_', '').replace('.', '').isalnum():
        return jsonify({'ok': False, 'msg': 'Usuário só pode conter letras, números, _ e .'})

    mesarios = load_mesarios()
    if usuario in mesarios:
        return jsonify({'ok': False, 'msg': 'Este usuário já existe.'})

    mesarios[usuario] = {
        'nome': nome,
        'senha_hash': hash_senha(senha),
        'admin': False,
        'senha_temporaria': True,  # Force password change on first login
        'criado_em': ts(),
        'criado_por': session.get('mesario_nome', '-')
    }
    save_mesarios(mesarios)
    return jsonify({'ok': True, 'msg': f'Mesário "{nome}" cadastrado. Ele deverá alterar a senha no primeiro acesso.'})

@app.route('/api/mesario/alterar_senha', methods=['POST'])
def alterar_senha():
    """Change password. A user can change their own password;
    an admin can change any user's password."""
    if not require_mesario():
        return jsonify({'ok': False, 'msg': 'Acesso restrito.'})
    dados = request.json or {}
    usuario_logado = session.get('mesario_usuario')
    usuario_alvo = dados.get('usuario', usuario_logado).strip().lower()
    senha_atual = dados.get('senha_atual', '')
    senha_nova = dados.get('senha_nova', '')
    senha_nova_conf = dados.get('senha_nova_conf', '')

    if not senha_nova or not senha_nova_conf:
        return jsonify({'ok': False, 'msg': 'Informe a nova senha e a confirmação.'})
    if senha_nova != senha_nova_conf:
        return jsonify({'ok': False, 'msg': 'Nova senha e confirmação não coincidem.'})
    if len(senha_nova) < 4:
        return jsonify({'ok': False, 'msg': 'Nova senha deve ter ao menos 4 caracteres.'})

    mesarios = load_mesarios()
    if usuario_alvo not in mesarios:
        return jsonify({'ok': False, 'msg': 'Usuário não encontrado.'})

    is_admin_logado = session.get('mesario_admin', False)
    is_proprio = (usuario_alvo == usuario_logado)

    # Permission: user can change own password; admin can change anyone's
    if not is_proprio and not is_admin_logado:
        return jsonify({'ok': False, 'msg': 'Apenas o administrador pode alterar a senha de outros usuários.'})

    # If changing OWN password, require current password
    # (admin changing own password also needs current password)
    if is_proprio:
        ok, _ = autenticar_mesario(usuario_logado, senha_atual)
        if not ok:
            return jsonify({'ok': False, 'msg': 'Senha atual incorreta.'})
    # Admin changing someone else's password does NOT need the target's current password

    if senha_nova == senha_atual and is_proprio:
        return jsonify({'ok': False, 'msg': 'A nova senha deve ser diferente da atual.'})

    mesarios[usuario_alvo]['senha_hash'] = hash_senha(senha_nova)
    # If admin reset someone else's password, force that user to change it on next login.
    # If user changed own password, clear the temporary flag.
    if is_proprio:
        mesarios[usuario_alvo]['senha_temporaria'] = False
    else:
        mesarios[usuario_alvo]['senha_temporaria'] = True
    mesarios[usuario_alvo]['senha_alterada_em'] = ts()
    mesarios[usuario_alvo]['senha_alterada_por'] = session.get('mesario_nome', '-')
    save_mesarios(mesarios)
    return jsonify({'ok': True, 'msg': 'Senha alterada com sucesso.'})

@app.route('/api/mesario/listar', methods=['GET'])
def listar_mesarios():
    if not require_mesario():
        return jsonify({'ok': False, 'msg': 'Acesso restrito.'})
    mesarios = load_mesarios()
    result = []
    for u, info in mesarios.items():
        result.append({
            'usuario': u,
            'nome': info.get('nome', u),
            'admin': info.get('admin', False),
            'criado_em': info.get('criado_em', '')
        })
    result.sort(key=lambda x: (not x['admin'], x['nome'].upper()))
    return jsonify({'ok': True, 'mesarios': result})

@app.route('/api/mesario/excluir', methods=['POST'])
def excluir_mesario():
    if not require_mesario():
        return jsonify({'ok': False, 'msg': 'Acesso restrito.'})
    dados = request.json
    usuario = dados.get('usuario', '').strip().lower()
    mesarios = load_mesarios()
    if usuario not in mesarios:
        return jsonify({'ok': False, 'msg': 'Mesário não encontrado.'})
    if mesarios[usuario].get('admin'):
        return jsonify({'ok': False, 'msg': 'Não é possível excluir o administrador.'})
    if usuario == session.get('mesario_usuario'):
        return jsonify({'ok': False, 'msg': 'Você não pode excluir a si mesmo.'})
    del mesarios[usuario]
    save_mesarios(mesarios)
    return jsonify({'ok': True})

# ─── ELEIÇÕES (público) ───────────────────────────────────────────────────────

@app.route('/api/eleicoes', methods=['GET'])
def get_eleicoes():
    """Public list: elections in progress + closed (not hidden)."""
    ids = lista_eleicoes()
    result = []
    for eid in ids:
        d = load_election(eid)
        if not d or d.get('oculta', False):
            continue
        # Include both open and closed (not hidden) elections
        if d.get('eleicao_aberta') or d.get('eleicao_encerrada'):
            result.append({
                'id': eid,
                'titulo': d.get('titulo', eid),
                'aberta': d.get('eleicao_aberta', False),
                'encerrada': d.get('eleicao_encerrada', False),
                'criada_em': d.get('criada_em', ''),
                'encerrada_em': d.get('encerrada_em', '')
            })
    return jsonify({'ok': True, 'eleicoes': result})

@app.route('/api/eleicoes/todas', methods=['GET'])
def get_todas_eleicoes():
    """Mesário list: all elections including hidden and closed."""
    if not require_mesario():
        return jsonify({'ok': False, 'msg': 'Acesso restrito.'})
    ids = lista_eleicoes()
    result = []
    for eid in ids:
        d = load_election(eid)
        if d:
            result.append({
                'id': eid,
                'titulo': d.get('titulo', eid),
                'aberta': d.get('eleicao_aberta', False),
                'encerrada': d.get('eleicao_encerrada', False),
                'oculta': d.get('oculta', False),
                'configurado': d.get('configurado', False),
                'criada_em': d.get('criada_em', ''),
                'total_votos': sum(d.get('votos', {}).values()) + d.get('votos_brancos', 0),
                'tem_planilha': len(d.get('funcionarios', [])) > 0
            })
    return jsonify({'ok': True, 'eleicoes': result})

@app.route('/api/eleicoes/criar', methods=['POST'])
def criar_eleicao():
    if not require_mesario():
        return jsonify({'ok': False, 'msg': 'Acesso restrito. Faça login como mesário.'})
    titulo = request.form.get('titulo', '').strip()
    if not titulo:
        return jsonify({'ok': False, 'msg': 'Informe um título para a eleição.'})

    # Process CSV or XLSX file
    funcionarios = []
    file = request.files.get('planilha')
    if file and file.filename:
        filename = file.filename.lower()
        try:
            if filename.endswith('.xlsx') or filename.endswith('.xls'):
                import openpyxl
                raw_bytes = file.read()
                wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), read_only=True, data_only=True)
                ws = wb.active
                header_map = {}
                header_row = None
                for row in ws.iter_rows(min_row=1, max_row=10):
                    for cell in row:
                        if cell.value is None:
                            continue
                        k = str(cell.value).strip().upper()
                        if k in ('NOME', 'NOME COMPLETO', 'NOME_COMPLETO', 'FUNCIONARIO', 'FUNCIONÁRIO', 'COLABORADOR'):
                            header_map[cell.column - 1] = 'nome'
                            header_row = cell.row
                        elif k in ('CPF', 'CPF_FUNCIONARIO', 'CPF_COLABORADOR', 'NR_CPF'):
                            header_map[cell.column - 1] = 'cpf'
                            header_row = cell.row
                    if header_map:
                        break
                if not header_map or 'nome' not in header_map.values() or 'cpf' not in header_map.values():
                    wb.close()
                    return jsonify({'ok': False, 'msg': 'Colunas NOME e CPF não encontradas na planilha XLSX.'})
                for row in ws.iter_rows(min_row=header_row + 1):
                    nome = None
                    cpf = None
                    for cell in row:
                        col_idx = cell.column - 1
                        if col_idx not in header_map or cell.value is None:
                            continue
                        v = str(cell.value).strip()
                        if header_map[col_idx] == 'nome':
                            nome = v if v else None
                        elif header_map[col_idx] == 'cpf':
                            cpf_clean = v.replace('.', '').replace('-', '').replace(' ', '')
                            if '.' in cpf_clean and cpf_clean.replace('.', '').isdigit():
                                try:
                                    cpf_clean = str(int(float(v)))
                                except:
                                    pass
                            if cpf_clean.isdigit() and len(cpf_clean) < 11:
                                cpf_clean = cpf_clean.zfill(11)
                            cpf = cpf_clean
                    if nome and cpf and len(cpf) == 11 and cpf.isdigit():
                        funcionarios.append({'nome': nome, 'cpf': cpf})
                wb.close()
                if not funcionarios:
                    return jsonify({'ok': False, 'msg': 'Nenhum funcionário válido na planilha XLSX.'})
            else:
                raw_bytes = file.read()
                try:
                    content = raw_bytes.decode('utf-8-sig')
                except UnicodeDecodeError:
                    try:
                        content = raw_bytes.decode('latin-1')
                    except UnicodeDecodeError:
                        content = raw_bytes.decode('utf-8', errors='replace')
                content = content.lstrip('\ufeff')
                first_line = content.split('\n')[0] if content else ''
                if ';' in first_line:
                    delimiter = ';'
                elif '\t' in first_line:
                    delimiter = '\t'
                elif ',' in first_line:
                    delimiter = ','
                else:
                    try:
                        dialect = csv.Sniffer().sniff(content[:2048])
                        delimiter = dialect.delimiter
                    except csv.Error:
                        delimiter = ';'
                reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
                for row in reader:
                    nome = None
                    cpf = None
                    for key, value in row.items():
                        if key is None or value is None:
                            continue
                        k = key.strip().strip('\ufeff').strip('"').strip("'").strip().upper()
                        v = value.strip().strip('"').strip("'").strip()
                        if k in ('NOME', 'NOME COMPLETO', 'NOME_COMPLETO', 'FUNCIONARIO', 'FUNCIONÁRIO', 'COLABORADOR'):
                            nome = v if v else None
                        elif k in ('CPF', 'CPF_FUNCIONARIO', 'CPF_COLABORADOR', 'NR_CPF'):
                            if v:
                                cpf = v.replace('.', '').replace('-', '').replace(' ', '')
                                if cpf.isdigit() and len(cpf) < 11:
                                    cpf = cpf.zfill(11)
                    if nome and cpf and len(cpf) == 11 and cpf.isdigit():
                        funcionarios.append({'nome': nome, 'cpf': cpf})
                if not funcionarios:
                    reader2 = csv.DictReader(io.StringIO(content), delimiter=delimiter)
                    cols = list(reader2.fieldnames) if reader2.fieldnames else []
                    cols_str = ', '.join(cols) if cols else 'nenhuma'
                    return jsonify({'ok': False, 'msg': f'Nenhum funcionário válido. Colunas detectadas: [{cols_str}].'})
        except Exception as e:
            return jsonify({'ok': False, 'msg': f'Erro ao processar planilha: {str(e)}'})
    else:
        return jsonify({'ok': False, 'msg': 'É obrigatório anexar a planilha de funcionários (CSV ou XLSX).'})

    eid = datetime.now().strftime('%Y%m%d_%H%M%S')
    data = {
        'titulo': titulo, 'configurado': False,
        'candidatos': [], 'votos': {},
        'votos_brancos': 0, 'cpfs_votantes': [],
        'eleicao_aberta': False, 'eleicao_encerrada': False,
        'oculta': False,
        'criada_em': ts(),
        'funcionarios': funcionarios
    }
    save_election(eid, data)
    append_log(eid, {'hora': ts(), 'evento': f'Eleição criada: {titulo} — {len(funcionarios)} funcionário(s) cadastrado(s)'})
    return jsonify({'ok': True, 'id': eid, 'total_funcionarios': len(funcionarios)})

@app.route('/api/eleicoes/<eid>/status', methods=['GET'])
def status(eid):
    d = load_election(eid)
    if not d:
        return jsonify({'ok': False, 'msg': 'Eleição não encontrada.'})
    return jsonify({
        'ok': True, 'titulo': d.get('titulo', ''),
        'configurado': d['configurado'],
        'eleicao_aberta': d['eleicao_aberta'],
        'eleicao_encerrada': d['eleicao_encerrada'],
        'oculta': d.get('oculta', False),
        'num_candidatos': len(d['candidatos']),
        'total_votos': sum(d['votos'].values()) + d.get('votos_brancos', 0),
        'total_funcionarios': len(d.get('funcionarios', []))
    })

# ─── MESÁRIO: GERENCIAR ELEIÇÕES ──────────────────────────────────────────────

@app.route('/api/eleicoes/<eid>/configurar', methods=['POST'])
def configurar(eid):
    if not require_mesario():
        return jsonify({'ok': False, 'msg': 'Acesso restrito. Faça login como mesário.'})
    d = load_election(eid)
    if not d:
        return jsonify({'ok': False, 'msg': 'Eleição não encontrada.'})
    if d.get('eleicao_aberta') or d.get('eleicao_encerrada'):
        return jsonify({'ok': False, 'msg': 'Eleição já iniciada ou encerrada.'})

    candidatos_json = request.form.get('candidatos', '[]')
    try:
        candidatos = json.loads(candidatos_json)
    except:
        return jsonify({'ok': False, 'msg': 'Dados de candidatos inválidos.'})

    if len(candidatos) < 1:
        return jsonify({'ok': False, 'msg': 'Informe ao menos 1 candidato.'})
    numeros = [c['numero'] for c in candidatos]
    if len(numeros) != len(set(numeros)):
        return jsonify({'ok': False, 'msg': 'Números de candidatos duplicados.'})

    pdir = photos_dir(eid)
    for i, cand in enumerate(candidatos):
        photo_key = f'foto_{i}'
        photo_file = request.files.get(photo_key)
        if photo_file and photo_file.filename:
            ext = photo_file.filename.rsplit('.', 1)[-1].lower() if '.' in photo_file.filename else 'jpg'
            if ext not in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
                ext = 'jpg'
            fname = f'{uuid.uuid4().hex}.{ext}'
            photo_file.save(os.path.join(pdir, fname))
            cand['foto'] = f'/fotos/{eid}/{fname}'
        else:
            cand['foto'] = ''

    d['candidatos'] = candidatos
    d['votos'] = {str(c['numero']): 0 for c in candidatos}
    d['configurado'] = True
    d['eleicao_aberta'] = True
    d['cpfs_votantes'] = []
    d['votos_brancos'] = 0
    save_election(eid, d)
    append_log(eid, {'hora': ts(), 'evento': f'Eleição iniciada com {len(candidatos)} candidato(s)'})
    return jsonify({'ok': True})

@app.route('/api/eleicoes/<eid>/encerrar', methods=['POST'])
def encerrar(eid):
    if not require_mesario():
        return jsonify({'ok': False, 'msg': 'Acesso restrito.'})
    d = load_election(eid)
    if not d:
        return jsonify({'ok': False, 'msg': 'Eleição não encontrada.'})
    d['eleicao_aberta'] = False
    d['eleicao_encerrada'] = True
    d['encerrada_em'] = ts()
    save_election(eid, d)
    append_log(eid, {'hora': ts(), 'evento': 'Eleição encerrada'})
    return jsonify({'ok': True})

@app.route('/api/eleicoes/<eid>/ocultar', methods=['POST'])
def ocultar(eid):
    """Hide from public list AND release all CPFs back for use in other elections.
    The election data itself (votes, results, log) is preserved."""
    if not require_mesario():
        return jsonify({'ok': False, 'msg': 'Acesso restrito.'})
    d = load_election(eid)
    if not d:
        return jsonify({'ok': False, 'msg': 'Eleição não encontrada.'})
    d['oculta'] = True
    save_election(eid, d)
    # Release CPFs so these voters can participate in other elections
    release_cpfs_for_election(eid)
    append_log(eid, {'hora': ts(), 'evento': 'Eleição ocultada — CPFs liberados para outras eleições'})
    return jsonify({'ok': True})

@app.route('/api/eleicoes/<eid>/exibir', methods=['POST'])
def exibir(eid):
    """Unhide election. NOTE: CPFs that voted here remain free — they were
    released on hide and can now vote anywhere. This is intentional."""
    if not require_mesario():
        return jsonify({'ok': False, 'msg': 'Acesso restrito.'})
    d = load_election(eid)
    if not d:
        return jsonify({'ok': False, 'msg': 'Eleição não encontrada.'})
    d['oculta'] = False
    save_election(eid, d)
    append_log(eid, {'hora': ts(), 'evento': 'Eleição reexibida na tela inicial'})
    return jsonify({'ok': True})

@app.route('/api/eleicoes/<eid>/excluir', methods=['POST'])
def excluir_eleicao(eid):
    """Securely delete an election. Requires the current mesário's password to confirm."""
    if not require_mesario():
        return jsonify({'ok': False, 'msg': 'Acesso restrito.'})
    dados = request.json or {}
    senha = dados.get('senha', '')
    usuario, nome = mesario_logado()
    # Re-validate the current mesário's own password
    ok, _ = autenticar_mesario(usuario, senha)
    if not ok:
        return jsonify({'ok': False, 'msg': 'Senha incorreta. A eleição NÃO foi excluída.'})
    d = load_election(eid)
    if not d:
        return jsonify({'ok': False, 'msg': 'Eleição não encontrada.'})

    # Archive a record of the deletion in the global history before removing
    titulo = d.get('titulo', eid)
    total_votos = sum(d.get('votos', {}).values()) + d.get('votos_brancos', 0)
    total_funcionarios = len(d.get('funcionarios', []))
    hist_entry = {
        'id': eid,
        'titulo': titulo,
        'criada_em': d.get('criada_em', ''),
        'encerrada_em': d.get('encerrada_em', ''),
        'excluida_em': ts(),
        'excluida_por': nome,
        'total_votos': total_votos,
        'total_funcionarios': total_funcionarios,
        'estava_encerrada': d.get('eleicao_encerrada', False)
    }
    append_global_history(hist_entry)

    # Release CPFs from global registry so they can vote in other elections
    release_cpfs_for_election(eid)

    # Delete folder
    shutil.rmtree(os.path.join(ELEICOES_DIR, eid), ignore_errors=True)
    return jsonify({'ok': True, 'msg': f'Eleição "{titulo}" excluída.'})

@app.route('/api/historico', methods=['GET'])
def historico_eleicoes():
    """Returns combined history: current elections (any status) + deleted ones."""
    if not require_mesario():
        return jsonify({'ok': False, 'msg': 'Acesso restrito.'})

    items = []
    # Current elections (any status)
    for eid in lista_eleicoes():
        d = load_election(eid)
        if not d:
            continue
        total = sum(d.get('votos', {}).values()) + d.get('votos_brancos', 0)
        if d.get('eleicao_encerrada'):
            estado = 'Encerrada'
        elif d.get('eleicao_aberta'):
            estado = 'Em andamento'
        else:
            estado = 'Pendente'
        items.append({
            'id': eid,
            'titulo': d.get('titulo', eid),
            'estado': estado,
            'criada_em': d.get('criada_em', ''),
            'encerrada_em': d.get('encerrada_em', ''),
            'total_votos': total,
            'total_funcionarios': len(d.get('funcionarios', [])),
            'oculta': d.get('oculta', False),
            'excluida': False
        })

    # Deleted elections from archive
    for h in load_global_history():
        items.append({
            'id': h.get('id', ''),
            'titulo': h.get('titulo', ''),
            'estado': 'Excluída',
            'criada_em': h.get('criada_em', ''),
            'encerrada_em': h.get('encerrada_em', ''),
            'excluida_em': h.get('excluida_em', ''),
            'excluida_por': h.get('excluida_por', ''),
            'total_votos': h.get('total_votos', 0),
            'total_funcionarios': h.get('total_funcionarios', 0),
            'oculta': False,
            'excluida': True
        })

    # Sort by creation date descending
    items.sort(key=lambda x: x.get('criada_em', ''), reverse=True)
    return jsonify({'ok': True, 'itens': items})

@app.route('/api/eleicoes/<eid>/zeresima', methods=['GET'])
def zeresima(eid):
    if not require_mesario():
        return jsonify({'ok': False, 'msg': 'Acesso restrito.'})
    d = load_election(eid)
    if not d:
        return jsonify({'ok': False})
    append_log(eid, {'hora': ts(), 'evento': 'Zerésima impressa'})
    return jsonify({'ok': True, 'titulo': d.get('titulo', ''),
                    'candidatos': d['candidatos'], 'gerada_em': ts()})

@app.route('/api/eleicoes/<eid>/log', methods=['GET'])
def get_log(eid):
    if not require_mesario():
        return jsonify({'ok': False, 'msg': 'Acesso restrito.'})
    return jsonify({'ok': True, 'log': load_log(eid)})

# ─── ELEITOR ──────────────────────────────────────────────────────────────────

@app.route('/api/eleicoes/<eid>/validar_cpf', methods=['POST'])
def validar_cpf(eid):
    dados = request.json
    cpf = dados.get('cpf', '').replace('.','').replace('-','').strip()
    if len(cpf) != 11 or not cpf.isdigit():
        return jsonify({'ok': False, 'msg': 'CPF inválido. Digite 11 dígitos.'})
    d = load_election(eid)
    if not d:
        return jsonify({'ok': False, 'msg': 'Eleição não encontrada.'})
    if not d['eleicao_aberta']:
        return jsonify({'ok': False, 'msg': 'Votação não está aberta.'})
    funcionarios = d.get('funcionarios', [])
    funcionario = None
    for f in funcionarios:
        if f['cpf'] == cpf:
            funcionario = f
            break
    if not funcionario:
        return jsonify({'ok': False, 'msg': 'CPF não encontrado na lista de funcionários autorizados.'})
    voted_eid = cpf_has_voted(cpf)
    if voted_eid:
        voted_d = load_election(voted_eid)
        titulo = voted_d.get('titulo', voted_eid) if voted_d else voted_eid
        return jsonify({'ok': False, 'msg': f'Este CPF já votou na eleição "{titulo}".'})
    return jsonify({'ok': True, 'nome_funcionario': funcionario['nome']})

@app.route('/api/eleicoes/<eid>/candidato/<numero>', methods=['GET'])
def get_candidato(eid, numero):
    d = load_election(eid)
    if not d: return jsonify({'ok': False})
    c = next((x for x in d['candidatos'] if str(x['numero']) == numero), None)
    return jsonify({'ok': bool(c), 'candidato': c})

@app.route('/api/eleicoes/<eid>/candidatos', methods=['GET'])
def get_candidatos_list(eid):
    """Public list of candidates (number + name) for the voting reference strip.
    Does NOT include vote counts."""
    d = load_election(eid)
    if not d: return jsonify({'ok': False})
    if not d.get('eleicao_aberta'):
        return jsonify({'ok': False, 'msg': 'Votação não está aberta.'})
    cands = [{'numero': c['numero'], 'nome': c['nome']} for c in d['candidatos']]
    cands.sort(key=lambda x: x['numero'])
    return jsonify({'ok': True, 'candidatos': cands})

@app.route('/api/eleicoes/<eid>/votar', methods=['POST'])
def votar(eid):
    dados = request.json
    cpf = dados.get('cpf', '').replace('.','').replace('-','').strip()
    numero = str(dados.get('numero', '')).strip()
    d = load_election(eid)
    if not d:
        return jsonify({'ok': False, 'msg': 'Eleição não encontrada.'})
    if not d['eleicao_aberta']:
        return jsonify({'ok': False, 'msg': 'Votação não está aberta.'})
    funcionarios = d.get('funcionarios', [])
    if not any(f['cpf'] == cpf for f in funcionarios):
        return jsonify({'ok': False, 'msg': 'CPF não autorizado.'})
    voted_eid = cpf_has_voted(cpf)
    if voted_eid:
        return jsonify({'ok': False, 'msg': 'CPF já votou em outra eleição.'})
    cpf_log = cpf[:3] + '.***.***-' + cpf[-2:]
    if numero == '00' or numero == '':
        d['votos_brancos'] = d.get('votos_brancos', 0) + 1
        d['cpfs_votantes'].append(cpf)
        save_election(eid, d)
        register_cpf_vote(cpf, eid)
        append_log(eid, {'hora': ts(), 'evento': 'Voto em BRANCO registrado', 'cpf': cpf_log})
        return jsonify({'ok': True, 'branco': True})
    if numero not in d['votos']:
        return jsonify({'ok': False, 'msg': 'Número de candidato inválido.'})
    d['votos'][numero] += 1
    d['cpfs_votantes'].append(cpf)
    save_election(eid, d)
    register_cpf_vote(cpf, eid)
    candidato = next((c for c in d['candidatos'] if str(c['numero']) == numero), None)
    nome_cand = candidato['nome'] if candidato else numero
    append_log(eid, {'hora': ts(), 'evento': f'Voto registrado — Nº {numero} ({nome_cand})', 'cpf': cpf_log})
    return jsonify({'ok': True, 'branco': False, 'candidato': candidato})

# ─── RESULTADO PÚBLICO (somente de eleição encerrada) ─────────────────────────

@app.route('/api/eleicoes/<eid>/resultado', methods=['GET'])
def resultado(eid):
    d = load_election(eid)
    if not d: return jsonify({'ok': False})
    # Only allow results of closed elections OR if mesário is logged in
    if not d.get('eleicao_encerrada') and not require_mesario():
        return jsonify({'ok': False, 'msg': 'Resultado disponível apenas após encerramento.'})
    result = []
    for c in d['candidatos']:
        result.append({
            'nome': c['nome'], 'numero': c['numero'],
            'foto': c.get('foto', ''),
            'votos': d['votos'].get(str(c['numero']), 0)
        })
    result.sort(key=lambda x: x['votos'], reverse=True)
    total = sum(r['votos'] for r in result) + d.get('votos_brancos', 0)
    total_funcionarios = len(d.get('funcionarios', []))
    return jsonify({
        'ok': True, 'titulo': d.get('titulo', ''),
        'candidatos': result,
        'votos_brancos': d.get('votos_brancos', 0),
        'total_votos': total,
        'total_funcionarios': total_funcionarios,
        'eleicao_aberta': d['eleicao_aberta'],
        'eleicao_encerrada': d['eleicao_encerrada'],
        'encerrada_em': d.get('encerrada_em', ''),
        'criada_em': d.get('criada_em', '')
    })

@app.route('/api/eleicoes/<eid>/relatorio_participacao', methods=['GET'])
def relatorio_participacao(eid):
    if not require_mesario():
        return jsonify({'ok': False, 'msg': 'Acesso restrito.'})
    d = load_election(eid)
    if not d:
        return jsonify({'ok': False, 'msg': 'Eleição não encontrada.'})
    funcionarios = d.get('funcionarios', [])
    cpfs_votantes = set(d.get('cpfs_votantes', []))
    votaram = []
    nao_votaram = []
    for f in funcionarios:
        cpf_masked = f['cpf'][:3] + '.***.***-' + f['cpf'][-2:]
        entry = {'nome': f['nome'], 'cpf_masked': cpf_masked}
        if f['cpf'] in cpfs_votantes:
            votaram.append(entry)
        else:
            nao_votaram.append(entry)
    votaram.sort(key=lambda x: x['nome'].upper())
    nao_votaram.sort(key=lambda x: x['nome'].upper())
    total = len(funcionarios)
    return jsonify({
        'ok': True,
        'titulo': d.get('titulo', ''),
        'votaram': votaram,
        'nao_votaram': nao_votaram,
        'total_funcionarios': total,
        'total_votaram': len(votaram),
        'total_nao_votaram': len(nao_votaram),
        'encerrada_em': d.get('encerrada_em', ''),
        'criada_em': d.get('criada_em', '')
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000)

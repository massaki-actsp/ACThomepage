# ACT-SP: PowerShell, GitHub, PythonAnywhere, Supabase e Registro.br

Guia revisado em 01/11/2026. Os ajustes locais foram preparados; o deploy, a
conexão com seu Supabase e a alteração do DNS ainda precisam ser executados nas
suas contas. Não há credenciais de produção neste documento.

## 1. Decisões e pré-requisitos

Este roteiro usa GitHub privado como transporte, PythonAnywhere para Flask/WSGI,
Supabase como PostgreSQL e `www.seudominio.com.br` como endereço público.
O navegador acessa HTML, assets e APIs no mesmo domínio. Somente o servidor
conecta ao PostgreSQL; nenhuma chave do banco vai para o JavaScript.

**Você precisará de plano pago do PythonAnywhere** para domínio próprio e banco
externo. Não precisa contratar o adicional PostgreSQL interno do PythonAnywhere:
o banco deste roteiro é o Supabase. Confira o plano no momento da contratação;
este guia não presume preço ou franquia fixos. Consulte
[domínios próprios](https://help.pythonanywhere.com/pages/CustomDomains/) e
[bancos externos](https://help.pythonanywhere.com/pages/KindsOfDatabases).

Substitua os exemplos antes de executar:

| Marcador | Substituir por |
| --- | --- |
| `SEU_GITHUB` | Usuário/organização dono do repositório GitHub |
| `SEU_PA` | Usuário do PythonAnywhere, não o usuário Admin do site |
| `seudominio.com.br` | Seu domínio real registrado |
| `webapp-XXXX.pythonanywhere.com` | Alvo exato mostrado na aba Web |
| `POOLER_HOST` / `PROJECT_REF` | Valores copiados do Connect do Supabase |

Se sua conta for da região europeia, use o painel e os hosts `.eu.pythonanywhere.com`
que ele indicar, inclusive o CNAME. Não copie o hostname ilustrativo deste guia.

O PDF anexado descreve CNAME e certificado. Aqui o fluxo foi ampliado para código,
banco e arquivos estáticos. O CNAME é o caminho recomendado para `www`; não deve
ser aplicado diretamente ao domínio raiz. O prazo de DNS depende do TTL e de
caches, não há garantia de propagação em 15 minutos ou duas horas.

## 2. Windows: ferramentas e login/logout do GitHub

Abra **Terminal → New Terminal → PowerShell** no VS Code:

```powershell
Set-Location 'C:\Users\massa\Documents\ACThomepage'
git --version
gh --version
```

Se faltar alguma ferramenta, instale e reabra o terminal:

```powershell
winget install --id Git.Git -e
winget install --id GitHub.cli -e
```

Git não tem um comando de login próprio. `git config user.name` e `user.email`
definem a autoria dos commits; a autenticação será feita pelo GitHub CLI.

```powershell
gh auth status
```

Se estiver conectado a uma conta antiga, execute somente para aquela conta:

```powershell
gh auth logout --hostname github.com --user USUARIO_ANTIGO
```

Depois entre na conta que deverá hospedar o projeto:

```powershell
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git --hostname github.com
gh auth status
```

Conclua a autenticação no navegador. O logout do `gh` não desconecta o navegador
nem a extensão de contas do VS Code. Não use senha da conta GitHub como senha de
`git push`; o CLI cuidará da autenticação. Referência:
[autenticação do GitHub CLI](https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git).

## 3. Criar o repositório e enviar a pasta

Na revisão deste guia, esta pasta ainda não era um repositório Git. Se você já
executou `git init` depois disso, pule essa inicialização e confira a branch.

```powershell
git init -b main
git config user.name 'SEU NOME'
git config user.email 'SEU_EMAIL_DE_COMMIT'
git status --short
```

O `.gitignore` incluído exclui `.env`, o ambiente virtual `ACThomepage/`, bancos
e logs em `instance/`, caches e material de trabalho. Não exclui o código,
templates, catálogo CSV ou imagens da aplicação.

```powershell
git check-ignore .env ACThomepage/Scripts/python.exe instance/actsp.db
git add .
git diff --cached --name-only
git diff --cached --stat
```

Antes do commit, confirme que nenhum `.env` real, banco, exportação de contatos
ou senha apareceu na lista. Se algum arquivo sensível foi adicionado por engano,
retire-o do staging com `git restore --staged -- 'CAMINHO_DO_ARQUIVO'` depois do
primeiro commit, ou `git rm --cached -- 'CAMINHO_DO_ARQUIVO'` no staging inicial;
isso não é um procedimento para apagar o arquivo local. Ajuste o `.gitignore`.

```powershell
git commit -m 'Preparar ACT-SP para PythonAnywhere'
$githubUser = gh api user --jq .login
gh repo create "$githubUser/ACThomepage" --private --source . --remote origin --push
git remote -v
```

Se o repositório remoto já existe, não execute `gh repo create` novamente:

```powershell
git remote add origin https://github.com/SEU_GITHUB/ACThomepage.git
git push -u origin main
```

Se `origin` também já existe, confira `git remote -v` antes de alterá-lo.
Não use `push --force`. Arquivos grandes precisam de atenção: o GitHub limita
arquivos enviados pelo Git a 100 MiB por arquivo. MP4 grande pode ser enviado
separadamente ao servidor; os vídeos YouTube/Vimeo não precisam de upload.

## 4. Supabase: criar o PostgreSQL e as tabelas

1. Crie/abra seu projeto no Supabase e guarde a senha do **banco**.
2. No **SQL Editor**, execute o conteúdo completo do `schema.sql` deste projeto.
3. Confirme as tabelas `contact_messages`, `agenda_events`, `mural_click_logs`
   e `admin_credentials`.
4. Em **Connect**, escolha **Session pooler** e copie a URI exata.
5. Use a porta `5432` do Session Pooler e acrescente `sslmode=require`.

Exemplo ilustrativo, não executável sem substituir os valores:

```text
postgresql://postgres.PROJECT_REF:SENHA_CODIFICADA@POOLER_HOST:5432/postgres?sslmode=require
```

Escolhemos Session Pooler para evitar dependência de IPv6 do endpoint direto.
Copie host e usuário do painel; não tente deduzir o host pela região. A senha na
URI precisa de percent-encoding se tiver caracteres reservados como `@`, `#`,
`/`, `:` ou `%`. Senha do banco, senha do Admin e senha do GitHub são distintas.
Não use a publishable/anon key como senha PostgreSQL.
[Conexões PostgreSQL do Supabase](https://supabase.com/docs/guides/database/connecting-to-postgres).

`sslmode=require` exige criptografia. Para validar também certificado e hostname,
baixe a CA indicada nas configurações SSL do Supabase e configure
`sslmode=verify-full&sslrootcert=/home/SEU_PA/ARQUIVO_CA.pem`. Não desabilite SSL
para contornar erro de conexão.

O `schema.sql` habilita RLS nas quatro tabelas e não cria políticas públicas.
Este backend usa a conexão de proprietário PostgreSQL, que pode operar nelas;
o navegador não deve acessar essas tabelas pela Data API. Não crie uma política
`USING (true)` para liberar o Admin.
[RLS e papéis do banco](https://supabase.com/docs/guides/database/postgres/row-level-security).

**Dados locais não são transferidos automaticamente.** Exportar mensagens/logs
antes da mudança serve como cópia, mas não importa esses dados no PostgreSQL.
A agenda e a senha já alterada no SQLite também permanecem no banco local.
Planeje uma migração separada se quiser preservar todo o histórico em produção.

## 5. PythonAnywhere: clonar o repositório privado

Abra **Consoles → Bash** na sua conta paga. Os comandos seguintes são **Bash**,
não PowerShell. Para não colocar token na URL de clone, use uma chave de deploy
somente de leitura, dedicada a este projeto:

```bash
mkdir -p ~/.ssh
ssh-keygen -t ed25519 -C "actsp-pythonanywhere" -f ~/.ssh/actsp_deploy
cat ~/.ssh/actsp_deploy.pub
```

Não sobrescreva uma chave existente. Escolha uma passphrase e guarde-a.
No GitHub: **repositório → Settings → Deploy keys → Add deploy key**. Cole apenas
a chave `.pub` e deixe **Allow write access desmarcado**. A chave privada
`actsp_deploy` fica no PythonAnywhere e nunca vai ao GitHub.

```bash
chmod 600 ~/.ssh/actsp_deploy
ssh -i ~/.ssh/actsp_deploy -o IdentitiesOnly=yes -T git@github.com
```

Na primeira conexão, confira a impressão digital do host contra a documentação
oficial do GitHub antes de aceitar. Uma mensagem de autenticação bem-sucedida
sem acesso a shell é normal; o comando pode sair com status 1.

```bash
cd ~
GIT_SSH_COMMAND="ssh -i $HOME/.ssh/actsp_deploy -o IdentitiesOnly=yes" git clone git@github.com:SEU_GITHUB/ACThomepage.git
cd ~/ACThomepage
git config core.sshCommand "ssh -i $HOME/.ssh/actsp_deploy -o IdentitiesOnly=yes"
git status
```

Se `~/ACThomepage` já existir, confira seu conteúdo em vez de apagar a pasta.
Para repositório público, HTTPS funciona sem autenticação, mas este roteiro
recomenda manter o projeto privado.

## 6. Criar o ambiente Python Linux

Não envie o ambiente virtual Windows. Crie outro no servidor. Exemplo com
Python 3.12: confirme que essa versão está disponível também no assistente Web.

```bash
python3.12 --version
mkvirtualenv --python=/usr/bin/python3.12 ACThomepage
cd ~/ACThomepage
python -m pip install -r requirements.txt
```

Se o painel oferecer outra versão compatível, use a mesma versão no virtualenv
e na aplicação Web. O projeto requer Python 3.10 ou superior. Para retornar ao
ambiente em uma nova console:

```bash
workon ACThomepage
cd ~/ACThomepage
```

Siga a opção de aplicação existente/manual da
[documentação Flask do PythonAnywhere](https://help.pythonanywhere.com/pages/Flask).

## 7. Criar o .env de produção no servidor

Somente no primeiro deploy, com `.env` ainda inexistente:

```bash
cd ~/ACThomepage
cp -n .env.pythonanywhere.example .env
chmod 600 .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from getpass import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass('Senha inicial do Admin: ')))"
nano .env
```

O primeiro comando Python gera `SECRET_KEY`; o segundo produz o hash de uma senha
digitada sem eco. Escolha uma senha inicial forte, com pelo menos 12 caracteres.
Copie os resultados para seus campos no editor. Não publique
esses valores. Guarde a chave e a senha com segurança. No `nano`, salve com
Ctrl+O, Enter e saia com Ctrl+X.

Preencha, por exemplo:

```dotenv
APP_ENV=production
FLASK_DEBUG=false
SECRET_KEY='COLE_O_SEGREDO_ALEATORIO_GERADO'
SESSION_COOKIE_SECURE=true
CREATE_TABLES=false
DATABASE_URL='postgresql://postgres.PROJECT_REF:SENHA_CODIFICADA@POOLER_HOST:5432/postgres?sslmode=require'
MURAL_LIBRARY_PATH=static/videos
MURAL_DATA_PATH=data/mural.csv
ADMIN_USERNAME=admin
ADMIN_PASSWORD=
ADMIN_PASSWORD_HASH='COLE_O_HASH_GERADO'
TRUSTED_PROXY_COUNT=1
```

O arquivo real está ignorado pelo Git. Não o copie para `static/`. Em atualizações,
mantenha a mesma `SECRET_KEY`; não recrie o `.env` nem gere senha nova a cada pull.
Senhas alteradas pela aba Segurança ficam no PostgreSQL e passam a prevalecer
sobre a senha inicial do ambiente.

O valor de proxy `1` usa a última entrada de `X-Forwarded-For`, conforme o proxy
do PythonAnywhere. Não use essa configuração em um servidor exposto diretamente;
localmente mantenha `0`. Sem isso, os logs podem mostrar o IP do balanceador.
[IP do cliente no PythonAnywhere](https://help.pythonanywhere.com/pages/WebAppClientIPAddresses).

## 8. Validar o backend antes de alterar DNS

Na console Bash, dentro do projeto e com o ambiente ativo:

```bash
python -m deploy.check_pythonanywhere
```

O verificador testa a conexão e as quatro tabelas sem inserir mensagens ou logs.
Também verifica rotas e assets com o cliente de teste Flask. Não imprime a URI
nem a senha. Este teste não substitui a verificação HTTP do servidor público.

Se falhar, resolva primeiro:

| Sintoma | Conferir |
| --- | --- |
| `SECRET_KEY`/produção inválida | Chave aleatória e `DATABASE_URL` preenchidos |
| Timeout/rede | Plano pago, host copiado, porta 5432 e restrições de rede do Supabase |
| IPv6 indisponível | Usar Session Pooler IPv4, não o endpoint direto |
| Password authentication failed | Senha do banco, percent-encoding e usuário `postgres.PROJECT_REF` |
| Tabela ausente | Executar `schema.sql` completo no projeto Supabase correto |
| `permission denied` | Papel PostgreSQL utilizado, RLS e privilégios desse papel |
| Import error | Ambiente ativado e dependências instaladas na mesma versão Python |

Se tiver habilitado restrições de rede no Supabase, confirme com o suporte do
PythonAnywhere quais IPs de saída precisam ser permitidos; não presuma que há
um único IP fixo nem libere o banco indiscriminadamente para resolver timeout.

## 9. Configurar a aplicação Web e WSGI

1. Na aba **Web**, clique **Add a new web app**.
2. Para teste inicial, pode usar o domínio da conta. Para o endereço final,
   configure o hostname completo `www.seudominio.com.br`.
3. Escolha **Manual configuration** e a mesma versão Python do virtualenv.
4. Configure **Source code** e **Working directory**:
   `/home/SEU_PA/ACThomepage`.
5. Em **Virtualenv**, informe `/home/SEU_PA/.virtualenvs/ACThomepage`.
6. Abra o **WSGI configuration file** pelo link do próprio painel.
7. Substitua o boilerplate pelo conteúdo de `deploy/pythonanywhere_wsgi.py`.
8. Salve e clique **Reload**.

O modelo usa `Path.home() / 'ACThomepage'`, portanto serve para o usuário Linux
logado sem hardcode de `SEU_PA`. Ajuste `PROJECT_DIR` se a pasta tiver outro nome.
Ele adiciona o projeto ao `sys.path`, carrega `.env` e importa `application`.
O arquivo WSGI configurado pelo painel fica normalmente em `/var/www/`; editar
somente o `wsgi.py` do projeto não altera automaticamente esse arquivo do painel.

**Não rode `python app.py` ou Gunicorn como servidor Web no PythonAnywhere.**
Ali a plataforma gerencia o WSGI/uWSGI. O comando `gunicorn wsgi:app` do Render
continua disponível, mas não é usado neste deploy.
[WSGI e erros de inicialização](https://help.pythonanywhere.com/pages/502BadGateway/).

Se preferir testar antes em `SEU_PA.pythonanywhere.com`, após os testes use o
lápis ao lado do nome da aplicação na aba Web para mudar para `www.seudominio.com.br`.
Isso altera o hostname da aplicação; não mantém automaticamente duas cópias do
site em paralelo. Depois confira novamente WSGI, DNS setup e certificado.

## 10. Arquivos estáticos: a correção de /css/ e /images/

O projeto foi ajustado para o namespace padrão Flask `/static/`. Os templates
usam `url_for('static', filename=...)`; o JavaScript do Mural recebe do HTML a
base das imagens. O domínio não está escrito no código.

Na aba **Web → Static files**, crie **somente este mapeamento principal**:

| URL | Directory |
| --- | --- |
| `/static/` | `/home/SEU_PA/ACThomepage/static` |

Remova mapeamentos antigos conflitantes de `/css/`, `/images/` e `/js/`, caso
tenham sido criados para esta versão anterior. Não mapeie `/` para a pasta do
projeto: isso pode expor código, `.env`, bancos ou substituir páginas dinâmicas.

Após **Reload**, confira diretamente:

```text
https://SEU_PA.pythonanywhere.com/static/css/style.css
https://SEU_PA.pythonanywhere.com/static/js/mural.js
https://SEU_PA.pythonanywhere.com/static/images/logo.png
```

Use o hostname real da aplicação quando ela já estiver no domínio próprio.
Se CSS ou imagem retornar 404, confira caminho Linux, maiúsculas/minúsculas e
mapeamento. Um arquivo `Logo.png` não é o mesmo que `logo.png` no Linux.
Referência: [mapeamento estático](https://help.pythonanywhere.com/pages/StaticFiles/).

As APIs continuam em `/api/...`; os MP4 locais continuam na rota
`/media/mural/ARQUIVO.mp4`, servida pelo Flask. Um vídeo local adicional pode ser
enviado pela aba **Files** para `static/videos/`, respeitando cota e tamanho de
upload do plano. Também ficará público em `/static/videos/` com este mapeamento;
não coloque vídeos privados ali. YouTube/Vimeo são definidos em `data/mural.csv`
e não dependem de upload de MP4. O pacote atual usa esses links em seus destaques.

## 11. Registro.br: CNAME do www

Só faça esta etapa depois de o backend e o WSGI estarem configurados.

1. No PythonAnywhere, confirme aplicação nomeada `www.seudominio.com.br`.
2. Em **DNS setup**, copie o **CNAME target** exato.
3. No Registro.br, entre no domínio e confira os servidores DNS autoritativos.
4. Se já usa DNS do Registro.br, abra **DNS → Editar zona/Modo avançado**.
5. Se o DNS estiver em outro provedor, edite a zona nesse provedor. Trocar
   nameservers sem replicar a zona pode derrubar e-mail e outros serviços.
6. Crie/ajuste a entrada abaixo e salve.

| Campo | Valor |
| --- | --- |
| Tipo | `CNAME` |
| Nome/entrada | `www` (ou o nome completo se a tela pedir assim) |
| Destino | `webapp-XXXX.pythonanywhere.com` copiado do painel |

O destino não leva `https://`, porta, `/mural.html` nem barra final. Não aponte
para `SEU_PA.pythonanywhere.com` se o painel forneceu outro CNAME. O alvo
`webapp-XXXX...` é um identificador DNS, não a URL para abrir o site.

Uma entrada CNAME não deve coexistir com registros A/AAAA ou outro CNAME para
esse mesmo `www`. Altere apenas registros conflitantes desse nome. Preserve
MX, SPF, DKIM, DMARC e outros registros de e-mail nos seus respectivos nomes.
Não altere nameservers ou DNSSEC sem um plano de migração da zona inteira.

No PowerShell do Windows:

```powershell
Resolve-DnsName -Name www.seudominio.com.br -Type CNAME
Resolve-DnsName -Name www.seudominio.com.br -Type CNAME -Server 1.1.1.1
```

O resultado deve mostrar o alvo que o painel forneceu. Aguarde caches expirarem
e confira se o aviso de DNS desaparece na aba Web. O CNAME resolve nomes; quem
entrega sua aplicação é a configuração WSGI do PythonAnywhere.

Referências: [PythonAnywhere/CNAME](https://help.pythonanywhere.com/pages/CustomDomains/)
e [DNS do Registro.br](https://registro.br/tecnologia/caracteristicas-tecnicas/).

## 12. Ativar HTTPS e acesso sem www

Com DNS reconhecido e o domínio respondendo, abra **Web → Security → HTTPS
certificate**, selecione **Auto-renewed Let's Encrypt certificate** e salve.
Confira `https://www.seudominio.com.br`. Depois ative **Force HTTPS** e recarregue.
O certificado para o domínio da conta não cobre automaticamente seu domínio próprio.
[Certificado](https://help.pythonanywhere.com/pages/HTTPSSetup) e
[Force HTTPS](https://help.pythonanywhere.com/pages/ForcingHTTPS).

Não coloque um CNAME na raiz `seudominio.com.br`. O endereço sem `www` é outro
hostname e precisa de redirecionamento próprio, preferencialmente com HTTPS
válido também na origem. Nesta primeira publicação, use o endereço completo
`https://www.seudominio.com.br` como endereço oficial.

**Atenção ao Registro.br:** seu redirecionador funciona no modo básico, não no
avançado, e afeta domínio e `www`. Não o ative por cima da zona avançada com o
CNAME deste roteiro. Para o domínio raiz, planeje um serviço de redirecionamento
compatível com a zona DNS mantida, ou uma segunda aplicação de redirect conforme
o PythonAnywhere; a segunda opção pode exigir outro recurso pago e manutenção
do DNS. Não crie A/AAAA com IP descoberto por acaso como solução definitiva.
[Limitações do redirecionamento Registro.br](https://registro.br/ajuda/gerenciamento-de-conta/)
e [domínio raiz no PythonAnywhere](https://help.pythonanywhere.com/pages/NakedDomains/).

## 13. Teste final pelo domínio real

```powershell
curl.exe -I https://www.seudominio.com.br/
curl.exe -I https://www.seudominio.com.br/static/css/style.css
Invoke-RestMethod https://www.seudominio.com.br/healthz
Invoke-RestMethod https://www.seudominio.com.br/api/mural
```

No navegador, confira Home, Mural, Contato e Admin. Envie uma mensagem claramente
identificada como teste pelo formulário; confirme no Admin e no Supabase. Clique
em um vídeo e confirme o log e IP. Teste também Agenda e exportações, depois troque
a senha na aba Segurança. Limpe apenas o registro de teste pelo painel, sem
resetar históricos reais. A rota `/healthz` informa que Flask responde, não
certifica sozinha que o banco ou todos os módulos estão funcionando.

Se um YouTube/Vimeo limitar incorporação por domínio, autorize seu hostname
final nas configurações do provedor de vídeo. Isso não é um ajuste de CNAME.

Se houver falha, consulte os links **Error log**, **Server log** e **Access log**
na aba Web. Erro 500 geralmente pede análise de aplicação/banco; 502 pode indicar
WSGI/importação; 404 de asset pede revisão de `/static/` e nomes dos arquivos.
Não compartilhe `.env`, URI do banco nem logs contendo dados de usuários.

## 14. Atualizações posteriores

No PowerShell local, com a conta GitHub correta:

```powershell
git status
git add app.py templates static data README.md docs deploy schema.sql requirements.txt .env.example .env.pythonanywhere.example .gitignore wsgi.py database.py
git diff --cached --stat
git commit -m 'Atualizar ACT-SP'
git push origin main
```

Adicione também outros arquivos de código alterados quando necessário. Não rode
esses comandos de commit se não houver mudanças. No Bash do PythonAnywhere:

```bash
workon ACThomepage
cd ~/ACThomepage
git status
git pull --ff-only origin main
python -m pip install -r requirements.txt
python -m deploy.check_pythonanywhere
```

Se houver mudanças de schema, aplique a migração necessária no Supabase antes do
reload; `CREATE TABLE IF NOT EXISTS` não altera automaticamente colunas de uma
tabela antiga. Clique **Reload** na aba Web e confira o site com Ctrl+F5. Preserve
`.env`, a chave SSH, os dados de produção e eventuais uploads não versionados.
Não use `git reset --hard` para resolver divergências sem entender suas mudanças.

## 15. O que foi e o que não foi executado

Feito localmente: leitura do PDF e da documentação, padronização de assets,
WSGI compatível, exemplo de ambiente, proteção de arquivos no Git, schema com
RLS e verificador de conexão. A pasta não foi publicada nem sua conta GitHub
foi desconectada. Nenhum domínio, certificado ou banco remoto foi alterado.
Os comandos acima são para você executar com seus dados reais e revisar cada
resultado antes da próxima etapa.

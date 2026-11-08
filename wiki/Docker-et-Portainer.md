# Héberger le serveur avec Docker ou Portainer

Ce parcours s’adresse à une installation hébergée. Pour un essai personnel sans serveur,
préférer l’[installation du plugin local](Installation.md).
Le plugin Claude fournit les commandes, skills, agents et hooks ; le conteneur fournit le serveur MCP HTTP.

## Préparer le code et la configuration privée

Installer Docker avec Compose v2, Git et le plugin Claude. Cloner le code dans un dossier distinct des
secrets et des données. Depuis le checkout du code :

```bash
git clone https://github.com/Hiobi/Genealogiste.git
cd Genealogiste
configuration_genealogiste="$HOME/.config/genealogiste-serveur"
mkdir -p "$configuration_genealogiste"
chmod 700 "$configuration_genealogiste"
cp .env.example "$configuration_genealogiste/serveur.env"
chmod 600 "$configuration_genealogiste/serveur.env"
export GENEALOGISTE_SERVEUR_ENV="$configuration_genealogiste/serveur.env"
```

Éditer ce fichier privé et renseigner `MCP_TOKEN` avec un jeton aléatoire propre à l’instance
(par exemple généré par `openssl rand -hex 32`). Ne pas réutiliser les jetons fictifs des tests.
Le modèle contient les réglages du backend ; `fichier` suffit pour commencer.

Pour transmettre ce fichier au conteneur sans le copier dans le checkout, créer un override privé :

```bash
cat > "$configuration_genealogiste/compose.prive.yml" <<'YAML'
services:
  mcp:
    env_file:
      - path: ${GENEALOGISTE_SERVEUR_ENV}
        required: true
YAML
```

Les valeurs de `environment` de la composition priment sur `env_file` ; `--env-file` ci-dessous sert aussi
aux interpolations, notamment `MCP_TOKEN`. Utiliser le même fichier pour les deux fonctions.

## Valider et démarrer

```bash
docker compose --env-file "$GENEALOGISTE_SERVEUR_ENV" \
  -f docker-compose.yml -f "$configuration_genealogiste/compose.prive.yml" config --quiet
docker compose --env-file "$GENEALOGISTE_SERVEUR_ENV" \
  -f docker-compose.yml -f "$configuration_genealogiste/compose.prive.yml" up -d --build
```

Le port MCP est publié sur `127.0.0.1:8765`, endpoint `/mcp`. Le volume `genealogiste_data` garde les données,
un autre volume garde le cache. Le processus utilise l’UID 10001 ; un montage de dossier existant demande
des droits compatibles, sans `chmod 777`. Le [guide d’exploitation](../docs/production.md) précise ces règles.

Pour démarrer aussi Gramps Web, ajouter `--profile gramps` avant `up` dans la même commande Compose.
Son interface est publiée sur `127.0.0.1:5055`. Créer les comptes et configurer le backend selon le
[guide Gramps](../docs/gramps-web.md) ; la présence du conteneur ne sélectionne pas automatiquement ce backend.

## Connecter Claude Code

Configurer le même jeton dans un terminal privé, sans le recopier dans un document partagé :

```bash
claude mcp add --scope local --transport http genealogiste http://127.0.0.1:8765/mcp \
  --header "Authorization: Bearer $MCP_TOKEN"
```

`MCP_TOKEN` doit être défini dans **ce terminal**, avec la valeur du fichier privé. Le fichier `.env` n’est
pas automatiquement exporté par le shell ; ne pas appeler cette commande avec une variable vide.
La commande enregistre la configuration cliente : garder les réglages locaux et ne pas les commiter.

Dans `/mcp`, désactiver le serveur stdio embarqué du plugin et ne garder que le serveur HTTP configuré.
Vérifier qu’un seul serveur est actif, puis demander `arbre_info`. Les hooks reconnaissent le nom
`genealogiste`. Pour un accès distant, utiliser un tunnel privé ou un proxy TLS authentifié ; ne pas
ouvrir directement Redis ou le port MCP à Internet.

## Portainer

Créer une stack depuis `https://github.com/Hiobi/Genealogiste`, avec `docker-compose.portainer.yml`.
Renseigner les variables dans Portainer à partir du [modèle de stack](../portainer/stack.env.example),
notamment `MCP_TOKEN` et, si choisi, le backend Gramps. Cette composition démarre MCP et Gramps sans profil.
Garder la publication locale par défaut et les volumes existants. Les identifiants sont propres à
chaque foyer/arbre ; ne pas copier ceux d’une autre installation.

## Mettre à jour ou arrêter

Conserver les fichiers privés et les mêmes options `--env-file` et `-f`. Mettre à jour le code puis refaire
`up -d --build`. Sauvegarder avant une migration. Un simple `down` arrête la stack ; **ne pas ajouter `-v`**
pour une mise à jour, car cela supprime les volumes.

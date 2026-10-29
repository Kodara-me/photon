# Photon

[![CI](https://github.com/jstmichel/photon/actions/workflows/ci.yml/badge.svg)](https://github.com/jstmichel/photon/actions/workflows/ci.yml)

*[English version](README.md)*

Photon est un petit service Linux qui applique une couleur RVB à un casque, une souris et un
clavier Logitech, à de la mémoire Corsair DDR5 et à une carte mère Gigabyte avec ses
ventilateurs. Il applique la couleur au démarrage, puis chaque fois qu’un appareil se
reconnecte, et laisse ensuite les appareils tranquilles. Pas de logiciel du fabricant, pas
d’interface graphique, pas de scrutation.

## Matériel pris en charge

Photon ne pilote que du matériel dont le protocole a été vérifié sur un vrai appareil. Tout
le reste est refusé plutôt que deviné.

| Appareil | Identifiant | Liaison |
|---|---|---|
| Casque Logitech G733 | `046d:0afe` | HID++ par USB |
| Souris Logitech G502 X Plus | `046d:c095`, ou son récepteur Lightspeed `046d:c547` | HID++ |
| Clavier Logitech PRO Gaming | `046d:c339` | HID++ par USB |
| Corsair Vengeance RGB DDR5 | `CMH64GX5M2B5600C40` | SMBus (`i2c-dev`) |
| Gigabyte Z790 AORUS ELITE AX, contrôleur ITE IT5701, micrologiciel 3.5.5.0 | `048d:5702` | HID par USB |

Le module de la carte mère règle ses huit emplacements d’éclairage, y compris les
ventilateurs branchés sur ses connecteurs RVB. Il ne touche qu’à l’éclairage : la vitesse
des ventilateurs et de la pompe reste gérée par leurs propres outils.

## Prérequis

- Linux avec systemd, la prise en charge `hidraw` du noyau et libudev (`systemd-libs` sur
  Arch et Fedora, `libudev1` sur Debian et Ubuntu).
- Pour la mémoire : `i2c-dev`, le pilote de l’adaptateur SMBus et les concentrateurs DDR5
  `spd5118` liés au noyau. Sans `/dev/i2c-*`, seule la mémoire est désactivée ; le reste
  fonctionne.
- Solaar et OpenRGB arrêtés : ils se disputent les mêmes appareils.

Le paquet autonome embarque son propre Python, hidapi et pyudev ; la machine n’a besoin ni
de Python ni de pip.

## Installation

### En une commande

```sh
curl -fsSL https://github.com/jstmichel/photon/releases/latest/download/get-photon.sh | sh
```

Le script télécharge le dernier paquet autonome, le vérifie avec le `SHA256SUMS` de la
version, lance `photon service check`, demande confirmation, puis lance
`sudo photon service install`. Il s’arrête tout de suite si cette version est déjà installée.
Options : `--version v0.1.0`, `--yes`, `--dry-run` (à passer avec `| sh -s -- --dry-run`).
Vous pouvez le lire avant : [scripts/get-photon.sh](scripts/get-photon.sh).

### À la main

Téléchargez le paquet autonome de la dernière version, vérifiez-le, puis installez le
service :

```sh
curl -LO https://github.com/jstmichel/photon/releases/latest/download/photon
curl -LO https://github.com/jstmichel/photon/releases/latest/download/SHA256SUMS
sha256sum --check --ignore-missing SHA256SUMS
chmod +x photon
./photon service check
sudo ./photon service install
```

`service check` signale les dépendances manquantes sans rien modifier ; l’installateur
n’installe aucun paquet et ne charge aucun module du noyau.

`service install` copie le paquet dans `/usr/local/lib/photon/photon`, crée le lien
`/usr/local/bin/photon`, écrit `/etc/systemd/system/photon.service`, puis active et démarre
le service. Le service tourne en root, car la mémoire demande un accès SMBus ; il a donc déjà
accès aux nœuds `hidraw` et aucune règle udev n’est installée. Relancer l’installation met à
jour et redémarre le service. Le fichier téléchargé peut ensuite être supprimé.

### Depuis KiraLights

Photon s’appelait auparavant KiraLights. Installer par-dessus une installation `kira-lights`
arrête et retire `kira-lights.service`, son exécutable et son lien de commande, et copie
`/etc/kira-lights/config.toml` vers `/etc/photon/config.toml` si aucune configuration Photon
n’existe encore. L’ancien fichier de configuration reste en place : supprimez
`/etc/kira-lights` une fois que Photon fonctionne comme prévu.

## Configuration

`/etc/photon/config.toml` contient la couleur ; il est créé à la première installation :

```toml
color = "#8B5CF6"
```

Après modification, appliquez-la avec `sudo photon service restart`. Le fichier est conservé
lors des mises à jour et de la désinstallation.

## Utilisation

```sh
photon service status
sudo photon service restart
journalctl -u photon.service -b
```

Le service attend que chaque contrôleur réponde avant d’écrire, réessaie jusqu’à quatre fois
en cas d’échec au démarrage, puis attend les arrivées d’appareils signalées par udev. Il
applique la couleur une fois et referme chaque appareil.

Les mêmes commandes s’utilisent à la main, pour un appareil ou pour tous :

```sh
sudo photon apply --color '#8B5CF6'
sudo photon apply --only ram --color '#FF0000'
sudo photon g733 --color '#00FF00' --zone 0
sudo photon motherboard --color '#8B5CF6'
```

Les sondes en lecture seule montrent ce que Photon voit, sans écrire de couleur :

```sh
sudo photon probe g502 --json
sudo photon probe ram --json
sudo photon probe motherboard --json
```

`photon --help` et `photon <commande> --help` listent toutes les options ; `--trace` affiche
les échanges du protocole.

## Windows

Sous Windows, Photon applique la couleur au Logitech G733, au G502 X Plus (filaire ou par
son récepteur), au clavier PRO et à la carte mère Gigabyte Z790 AORUS ELITE AX, ainsi qu’à
la RAM Corsair Vengeance RGB DDR5, depuis la ligne de commande ou comme service en
arrière-plan qui applique la couleur au démarrage, à la reprise et à chaque reconnexion d’un
appareil. `photon apply` signale chaque appareil qu’il n’a pas pu atteindre, avec la raison,
et applique les autres.

Prérequis : Windows 10 ou 11 et `photon.exe` (compilé avec `python tools\build_bundle.py`, qui
produit `dist\photon.exe`). Les appareils Logitech et la carte mère ne demandent aucun pilote.

La RAM demande [PawnIO](https://pawnio.eu), un pilote signé que vous installez vous-même avec
son installateur officiel ; Photon n’installe, ne met à jour et ne supprime aucun pilote.
`photon.exe` embarque le module SMBus i801 signé de PawnIO et utilise `PawnIOLib.dll` dans
`%ProgramFiles%\PawnIO`. La RAM n’est atteinte que depuis une **invite de commandes
élevée** (Exécuter en tant qu’administrateur). Sans PawnIO, sans élévation, ou tant qu’un
autre programme tient le mutex SMBus de Windows, la RAM est signalée comme indisponible avec
la raison et les autres appareils sont quand même appliqués. Fermez les moniteurs matériels
qui lisent le SMBus si le mutex reste occupé.

Désactivez d’abord l’éclairage des logiciels constructeurs. Photon n’arrête, ne reconfigure
et ne détecte aucun autre logiciel, et un appareil qu’un autre programme occupe est signalé
comme indisponible :

1. Dans Logitech G HUB, ouvrez chaque appareil, allez dans ses réglages d’éclairage et
   coupez l’éclairage (ou quittez G HUB).
2. Dans les Paramètres de Windows, ouvrez Personnalisation, Éclairage dynamique et
   désactivez « Utiliser l’éclairage dynamique sur mes appareils » (ou désactivez-le pour les
   appareils gérés par Photon).

Lancez ensuite Photon depuis une invite de commandes :

```bat
photon.exe apply --color "#8B5CF6"
photon.exe g733 --color "#00FF00" --zone 0
photon.exe probe g502 --json
```

Les options et la sortie sont les mêmes que sous Linux. Sans `--color`, la couleur vient de
`%ProgramData%\Photon\config.toml`, au même format que sous Linux ; si le fichier est
absent, la couleur par défaut s’applique.

### Service Windows

Téléchargez `photon.exe` et `SHA256SUMS` depuis la dernière version, puis vérifiez le fichier :

```bat
certutil -hashfile photon.exe SHA256
```

L’empreinte doit correspondre à la ligne `photon.exe` de `SHA256SUMS`. Ensuite, depuis une
**invite de commandes élevée** (Exécuter en tant qu’administrateur) :

```bat
photon.exe service check
photon.exe service install
```

`service check` signale les prérequis manquants sans rien modifier ; l’absence de PawnIO ne
désactive que la RAM. `service install` :

- copie l’exécutable dans `%ProgramFiles%\Photon\photon.exe` ;
- crée `%ProgramData%\Photon\config.toml` avec la couleur par défaut s’il est absent, dans
  un dossier que seuls les administrateurs et SYSTEM peuvent modifier ;
- crée le service `Photon`, exécuté sous LocalSystem, en démarrage automatique (non différé),
  avec `PlugPlay` pour seule dépendance et un redémarrage en cas d’échec, puis le démarre.

Relancer l’installation met à jour l’exécutable et redémarre le service. Le service démarre
pendant le démarrage de Windows, avant que quiconque ouvre une session, et applique la
couleur configurée à tous les appareils disponibles : l’écran de connexion l’affiche déjà. Il
applique de nouveau la couleur à la reprise après veille ou hibernation, y compris la mise
sous tension qui suit un Arrêt avec démarrage rapide, et chaque fois qu’un appareil pris en
charge est branché ou se reconnecte. Si le pilote PawnIO se charge après le démarrage du
service, la RAM est réessayée pendant quelques minutes. Son journal est
`%ProgramData%\Photon\photon.log`.

```bat
photon.exe service status
photon.exe service restart
```

`restart`, `install` et `uninstall` demandent une invite élevée et ne changent rien sans elle.
Après avoir modifié `%ProgramData%\Photon\config.toml`, appliquez-le avec
`photon.exe service restart`.

#### Vérifier le service à la main

L’écran de connexion ne se vérifie pas par un test. Après l’installation, service démarré,
mettez d’abord tous les appareils sur une autre couleur pour que la vérification se voie :
`photon.exe apply --color "#FF0000"`.

1. **Redémarrage.** Dans le menu Démarrer, choisissez Redémarrer. À l’écran de connexion, sans
   ouvrir de session, chaque appareil pris en charge branché affiche la couleur configurée.
2. **Arrêt avec démarrage rapide.** Mettez une autre couleur comme ci-dessus, choisissez
   Arrêter (démarrage rapide activé, par défaut), puis rallumez la machine. À l’écran de
   connexion, chaque appareil pris en charge branché affiche la couleur configurée.
3. **Reprise après veille.** Mettez une autre couleur comme ci-dessus, choisissez Mettre en
   veille dans le menu Démarrer, attendez que la machine soit en veille, puis réveillez-la au
   clavier ou avec le bouton d’alimentation. Sur l’écran de verrouillage, sans ouvrir de
   session, chaque appareil pris en charge branché affiche la couleur configurée. Répétez avec
   l’hibernation (`shutdown /h`) si vous le souhaitez. `%ProgramData%\Photon\photon.log`
   contient alors une ligne `resumed from sleep or hibernation`.
4. **Reconnexion.** Débranchez un appareil pris en charge (ou éteignez puis rallumez le G733),
   puis rebranchez-le : il affiche de nouveau la couleur configurée.

## Désinstallation

```sh
sudo photon service uninstall
```

La commande retire le service, l’exécutable et le lien de commande, et conserve
`/etc/photon/config.toml`.

Sous Windows, depuis une invite élevée :

```bat
photon.exe service uninstall
```

La commande arrête et retire le service et `%ProgramFiles%\Photon\photon.exe`, et conserve
`%ProgramData%\Photon\config.toml`.

## Compilation depuis les sources

```sh
python3 tools/build_bundle.py
build/venv/bin/python -m unittest discover -s tests -p 'test_*.py'
sudo dist/photon service install
```

La compilation installe les dépendances figées de `requirements-build.txt` dans `build/venv`
et produit `dist/photon`, un binaire Linux pour l’architecture de la machine de compilation.
Compilez sur un système dont la glibc n’est pas plus récente que celle de la cible. La
compilation n’installe et ne démarre rien.

La conception est décrite dans [docs/PLAN.md](docs/PLAN.md), et chaque étape vérifiée, avec
ses observations sur le matériel, dans [docs/slices/](docs/slices/) (en anglais).

## Contribuer

Les idées, les rapports de bogue et le nouveau matériel sont les bienvenus : voir
[CONTRIBUTING.md](CONTRIBUTING.md) (en anglais).

## Licence

[MIT](LICENSE)

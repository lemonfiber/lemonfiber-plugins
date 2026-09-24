# lemonfiber plugins

**Plugins a person has read, for your lemonfiber stack.** A plugin adds a
service to the stack lemonfiber runs for you: lemonfiber writes its container,
puts it on the stack's dashboard and, for a service the household uses, behind
the stack's proxy, and adds its checks to `lemonfiber doctor`. This list is where you find the ones somebody has reviewed.

## The plugins

| Plugin | What it gives you | Reviewed revision |
| --- | --- | --- |
| [Komga](https://github.com/lemonfiber/plugin-komga) | Read comics, manga and digital magazines in a browser, and on the reading apps you already use | [`plugins/komga.toml`](plugins/komga.toml) |
| [Uptime Kuma](https://github.com/lemonfiber/plugin-uptime-kuma) | Watch the services and connections your stack depends on, and see which one stopped answering | [`plugins/uptime-kuma.toml`](plugins/uptime-kuma.toml) |

Each plugin's own README says what it needs, what it changes on your machine,
what it sends anywhere, and how to install, update and remove it.

## Installing one

You need a lemonfiber with the `lemonfiber plugin` commands; lemonfiber 0.15.0
and earlier do not have them. lemonfiber installs a plugin from a directory on
your machine, so get a copy of the plugin's repository at the revision listed
here, then install it:

```sh
git clone https://github.com/lemonfiber/plugin-komga.git
git -C plugin-komga checkout <revision from plugins/komga.toml>
lemonfiber plugin install plugin-komga --dry-run
lemonfiber plugin install plugin-komga
```

`--dry-run` says everything the install would do and writes nothing.

lemonfiber does not read this repository. Nothing here is fetched when you
install, update or run a plugin, and a plugin you install from anywhere else is
checked the same way.

## What "reviewed" means

Every plugin listed here has passed two things, at the exact revision listed:

- **Automatic checks.** Its manifest is held to the schema, capabilities and
  extension points lemonfiber publishes, every proof it declares is run against
  the responses it recorded from its service, and every place it declares it
  may reach is checked. A registration failing any of it is refused.
- **A person reading it.** Somebody read the plugin at that revision and
  accepted it.

A review is of the plugin, not of the software it installs. A container image
is not something anybody can read line by line, which is why every plugin pins
its image to one exact build rather than a name its publisher could move.

The revision is a full commit, so what you install at that commit is what was
reviewed.

## Getting help

- **A question:** ask on [Discord](https://discord.nightworks.io).
- **Something wrong with a plugin:** open an issue on that plugin's repository.
- **Something wrong with this list:**
  [open an issue on this repository](https://github.com/lemonfiber/lemonfiber-plugins/issues).

## Licence

The registry data in this repository is under the Hippocratic License 3.0
(HL3-CORE); see [LICENSE](LICENSE). Each registered plugin carries its own
licence in its own repository.

## Adding a plugin to this list

How to register a plugin, and what CI checks on a registration:
[docs/development.md](docs/development.md).

import random
import re

import d20
import discord
from d20 import roll
from discord.ext import commands

from cogs5e.funcs import attackutils, checkutils, targetutils
from cogs5e.funcs.dice import old_roll
from cogs5e.funcs.lookupFuncs import select_monster_full, select_spell_full
from cogs5e.funcs.scripting import helpers
from cogs5e.models import embeds
from cogs5e.models.embeds import add_fields_from_args
from cogs5e.models.monster import Monster
from cogsmisc.stats import Stats
from utils.argparser import argparse
from utils.constants import SKILL_NAMES
from utils.dice import ContextPersistingRoller, VerboseMDStringifier
from utils.functions import search_and_select, try_delete


class Dice(commands.Cog):
    """Dice and math related commands."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='2', hidden=True)
    async def quick_roll(self, ctx, *, mod: str = '0'):
        """Quickly rolls a d20."""
        rollStr = '1d20+' + mod
        await ctx.invoke(self.rollCmd, rollStr=rollStr)

    @commands.command(name='roll', aliases=['r'])
    async def rollCmd(self, ctx, *, rollStr: str = '1d20'):
        """Rolls dice in xdy format.
        __Examples__
        !r xdy Attack!
        !r xdy+z adv Attack with Advantage!
        !r xdy-z dis Hide with Heavy Armor!
        !r xdy+xdy*z
        !r XdYkhZ
        !r 4d6mi2[fire] Elemental Adept, Fire
        !r 2d6e6 Explode on 6
        !r 10d6ra6 Spell Bombardment
        !r 4d6ro<3 Great Weapon Master
        __Supported Operators__
        k (keep)
        p (drop)
        ro (reroll once)
        rr (reroll infinitely)
        mi/ma (min/max result)
        e (explode dice of value)
        ra (reroll and add)
        __Supported Selectors__
        lX (lowest X)
        hX (highest X)
        >X/<X (greater than or less than X)"""

        if rollStr == '0/0':  # easter eggs
            return await ctx.send("What do you expect me to do, destroy the universe?")

        rollStr, adv = self._string_search_adv(rollStr)

        res = roll(rollStr, advantage=adv, allow_comments=True, stringifier=VerboseMDStringifier())
        out = f"{ctx.author.mention}  :game_die:\n" \
              f"{str(res)}"
        if len(out) > 1999:
            out = f"{ctx.author.mention}  :game_die:\n" \
                  f"{str(res)[:100]}...\n" \
                  f"**Total:** {res.total}"

        await try_delete(ctx.message)
        await ctx.send(out)
        await Stats.increase_stat(ctx, "dice_rolled_life")

    @commands.command(name='multiroll', aliases=['rr'])
    async def rr(self, ctx, iterations: int, rollStr, *, args=''):
        """Rolls dice in xdy format a given number of times.
        Usage: !rr <iterations> <xdy> [args]"""
        if iterations < 1 or iterations > 100:
            return await ctx.send("Too many or too few iterations.")
        results = []
        args, adv = self._string_search_adv(args)
        ast = d20.parse(rollStr)
        roller = ContextPersistingRoller()

        for _ in range(iterations):
            res = roller.roll(ast, advantage=adv)
            results.append(res)

        header = f"Rolling {iterations} iterations..."
        footer = f"{sum(o.total for o in results)} total."
        result_strs = '\n'.join([str(o) for o in results])

        out = f"{header}\n{result_strs}\n{footer}"

        if len(out) > 1500:
            one_result = str(results[0])[:100]
            one_result = f"{one_result}..." if len(one_result) > 100 else one_result
            out = f"{header}\n{one_result}\n{footer}"

        await try_delete(ctx.message)
        await ctx.send(f"{ctx.author.mention}\n{out}")
        await Stats.increase_stat(ctx, "dice_rolled_life")

    @commands.command(name='iterroll', aliases=['rrr'])
    async def rrr(self, ctx, iterations: int, rollStr, dc: int = 0, *, args=''):
        """Rolls dice in xdy format, given a set dc.
        Usage: !rrr <iterations> <xdy> <DC> [args]"""
        if iterations < 1 or iterations > 100:
            return await ctx.send("Too many or too few iterations.")
        results = []
        successes = 0
        args, adv = self._string_search_adv(args)
        ast = d20.parse(rollStr)
        roller = ContextPersistingRoller()

        for _ in range(iterations):
            res = roller.roll(ast, advantage=adv)
            if res.total >= dc:
                successes += 1
            results.append(res)

        header = f"Rolling {iterations} iterations, DC {dc}..."
        footer = f"{successes} successes, {sum(o.total for o in results)} total."
        result_strs = '\n'.join([str(o) for o in results])

        out = f"{header}\n{result_strs}\n{footer}"

        if len(out) > 1500:
            one_result = str(results[0])[:100]
            one_result = f"{one_result}..." if len(one_result) > 100 else one_result
            out = f"{header}\n{one_result}\n{footer}"

        await try_delete(ctx.message)
        await ctx.send(ctx.author.mention + '\n' + out)
        await Stats.increase_stat(ctx, "dice_rolled_life")

    @commands.group(aliases=['ma', 'monster_attack'], invoke_without_command=True)
    async def monster_atk(self, ctx, monster_name, atk_name=None, *, args=''):
        """Rolls a monster's attack.
        __Valid Arguments__
        -t "<target>" - Sets targets for the attack. You can pass as many as needed. Will target combatants if channel is in initiative.
        -t "<target>|<args>" - Sets a target, and also allows for specific args to apply to them. (e.g, -t "OR1|hit" to force the attack against OR1 to hit)

        adv/dis
        -ac [target ac]
        -b [to hit bonus]
        -d [damage bonus]
        -d# [applies damage to the first # hits]
        -rr [times to reroll]
        -t [target]
        -phrase [flavor text]
        crit (automatically crit)
        -h (hides monster name, image, and rolled values)
        """
        if atk_name is None or atk_name == 'list':
            return await ctx.invoke(self.monster_atk_list, monster_name)

        await try_delete(ctx.message)

        monster = await select_monster_full(ctx, monster_name)
        attacks = monster.attacks

        attack = await search_and_select(ctx, attacks, atk_name, lambda a: a.name)
        args = await helpers.parse_snippets(args, ctx)
        args = argparse(args)

        embed = discord.Embed()
        if not args.last('h', type_=bool):
            embed.set_thumbnail(url=monster.get_image_url())

        caster, targets, combat = await targetutils.maybe_combat(ctx, monster, args)
        await attackutils.run_attack(ctx, embed, args, caster, attack, targets, combat)

        embed.colour = random.randint(0, 0xffffff)
        if monster.source == 'homebrew':
            embeds.add_homebrew_footer(embed)

        await ctx.send(embed=embed)

    @monster_atk.command(name="list")
    async def monster_atk_list(self, ctx, monster_name):
        await try_delete(ctx.message)

        monster = await select_monster_full(ctx, monster_name)
        monster_name = monster.get_title_name()
        return await ctx.send(f"{monster_name}'s attacks:\n{monster.attacks.build_str(monster)}")

    @commands.command(aliases=['mc'])
    async def monster_check(self, ctx, monster_name, check, *args):
        """Rolls a check for a monster.
        __Valid Arguments__
        *adv/dis*
        *-b [conditional bonus]*
        -phrase [flavor text]
        -title [title] *note: [name] and [cname] will be replaced automatically*
        -dc [dc]
        -rr [iterations]
        str/dex/con/int/wis/cha (different skill base; e.g. Strength (Intimidation))
        -h (hides name and image of monster)

        An italicized argument means the argument supports ephemeral arguments - e.g. `-b1` applies a bonus to one check.
        """

        monster: Monster = await select_monster_full(ctx, monster_name)

        skill_key = await search_and_select(ctx, SKILL_NAMES, check, lambda s: s)

        embed = discord.Embed()
        embed.colour = random.randint(0, 0xffffff)

        args = await helpers.parse_snippets(args, ctx)
        args = argparse(args)

        checkutils.run_check(skill_key, monster, args, embed)

        if args.last('image') is not None:
            embed.set_thumbnail(url=args.last('image'))
        elif not args.last('h', type_=bool):
            embed.set_thumbnail(url=monster.get_image_url())

        if monster.source == 'homebrew':
            embeds.add_homebrew_footer(embed)

        await ctx.send(embed=embed)
        await try_delete(ctx.message)

    @commands.command(aliases=['ms'])
    async def monster_save(self, ctx, monster_name, save_stat, *args):
        """Rolls a save for a monster.
        __Valid Arguments__
        adv/dis
        -b [conditional bonus]
        -phrase [flavor text]
        -title [title] *note: [name] and [cname] will be replaced automatically*
        -dc [dc]
        -rr [iterations]
        -h (hides name and image of monster)"""

        monster: Monster = await select_monster_full(ctx, monster_name)

        embed = discord.Embed()
        embed.colour = random.randint(0, 0xffffff)

        args = await helpers.parse_snippets(args, ctx)
        args = argparse(args)

        checkutils.run_save(save_stat, monster, args, embed)

        if args.last('image') is not None:
            embed.set_thumbnail(url=args.last('image'))
        elif not args.last('h', type_=bool):
            embed.set_thumbnail(url=monster.get_image_url())

        if monster.source == 'homebrew':
            embeds.add_homebrew_footer(embed)

        await ctx.send(embed=embed)
        await try_delete(ctx.message)

    @commands.command(aliases=['mcast'])
    async def monster_cast(self, ctx, monster_name, spell_name, *args):
        """
        Casts a spell as a monster.
        __Valid Arguments__
        -i - Ignores Spellbook restrictions, for demonstrations or rituals.
        -l <level> - Specifies the level to cast the spell at.
        noconc - Ignores concentration requirements.
        -h - Hides rolled values.
        **__Save Spells__**
        -dc <Save DC> - Overrides the spell save DC.
        -save <Save type> - Overrides the spell save type.
        -d <damage> - Adds additional damage.
        pass - Target automatically succeeds save.
        fail - Target automatically fails save.
        adv/dis - Target makes save at advantage/disadvantage.
        **__Attack Spells__**
        See `!a`.
        **__All Spells__**
        -phrase <phrase> - adds flavor text.
        -title <title> - changes the title of the cast. Replaces [sname] with spell name.
        -thumb <url> - adds an image to the cast.
        -dur <duration> - changes the duration of any effect applied by the spell.
        -mod <spellcasting mod> - sets the value of the spellcasting ability modifier.
        int/wis/cha - different skill base for DC/AB (will not account for extra bonuses)
        """
        await try_delete(ctx.message)
        monster: Monster = await select_monster_full(ctx, monster_name)

        args = await helpers.parse_snippets(args, ctx)
        args = argparse(args)

        if not args.last('i', type_=bool):
            spell = await select_spell_full(ctx, spell_name, list_filter=lambda s: s.name in monster.spellbook)
        else:
            spell = await select_spell_full(ctx, spell_name)

        caster, targets, combat = await targetutils.maybe_combat(ctx, monster, args)
        result = await spell.cast(ctx, caster, targets, args, combat=combat)

        # embed display
        embed = result['embed']
        embed.colour = random.randint(0, 0xffffff)

        add_fields_from_args(embed, args.get('f'))

        if args.last('thumb') is not None:
            embed.set_thumbnail(url=args.last('thumb'))
        elif not args.last('h', type_=bool):
            embed.set_thumbnail(url=monster.get_image_url())

        if monster.source == 'homebrew':
            embeds.add_homebrew_footer(embed)

        # save changes: combat state
        if combat:
            await combat.final()
        await ctx.send(embed=embed)

    @staticmethod
    def _string_search_adv(rollstr):
        adv = d20.AdvType.NONE
        if re.search('(^|\s+)(adv|dis)(\s+|$)', rollstr) is not None:
            adv = d20.AdvType.ADV if re.search('(^|\s+)adv(\s+|$)', rollstr) is not None else d20.AdvType.DIS
            rollstr = re.sub('(adv|dis)(\s+|$)', '', rollstr)
        return rollstr, adv


def setup(bot):
    bot.add_cog(Dice(bot))

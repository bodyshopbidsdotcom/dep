# Example usage:
# python dependencies_updates.py -r "required value" positional_argument
import argparse
import sys

def run():
  parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
  parser.add_argument('-r', '--required-argument', required=True, help='Description of required argument')
  parser.add_argument('-d', '--defaulted-argument', default='default value', help='Description of defaulted argument')
  parser.add_argument('positional_argument', help='Description of the positional argument')

  sys.exit(dependencies_updates(parser.parse_args()))

def dependencies_updates(args):
  print('You have successfully created the new snippet "dependencies_updates"!')
  print('--------------------------------------------------------')
  print('required_argument: [%s]' % args.required_argument)
  print('defaulted_argument: [%s]' % args.defaulted_argument)
  print('positional_argument: [%s]' % args.positional_argument)
  return 0

if __name__ == "__main__":
  run()

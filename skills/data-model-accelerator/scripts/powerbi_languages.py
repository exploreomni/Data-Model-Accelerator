"""Positive M/DAX grammars for the authored billing pilot; never native execution.

Unknown syntax and functions fail. There is no eval/exec, source import, network,
file reader, connector execution or fallback to precomputed source outputs.
"""
from datetime import date
from decimal import Decimal, localcontext
import re


class LanguageError(ValueError): pass


class Tokens:
    def __init__(self, text, pattern):
        if not isinstance(text,str) or len(text)>100000: raise LanguageError('Invalid expression size')
        self.items=[];self.at=0;offset=0
        while offset<len(text.rstrip()):
            match=pattern.match(text,offset)
            if not match: raise LanguageError('Unsupported expression token at '+str(offset))
            self.items.append(match.group(1));offset=match.end()
        if len(self.items)>15000: raise LanguageError('Expression token limit')
    def peek(self): return self.items[self.at] if self.at<len(self.items) else ''
    def take(self,value=None):
        token=self.peek()
        if not token or (value is not None and token!=value): raise LanguageError('Expected '+str(value)+', found '+token)
        self.at+=1;return token
    def finish(self,node):
        if self.peek(): raise LanguageError('Trailing expression content: '+self.peek())
        return node


M_TOKEN=re.compile(r'\s*(#"(?:[^"]|"")*"|"(?:[^"]|"")*"|#table|[A-Za-z_][A-Za-z_0-9.]*|\d+|[{}\[\](),=+*-])')


class MParser(Tokens):
    def __init__(self,text): super().__init__(text,M_TOKEN)
    def name(self):
        value=self.take()
        if value.startswith('#"'): return value[2:-1].replace('""','"')
        if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9.]*|#table',value): raise LanguageError('M identifier required')
        return value
    def parse(self):
        if self.peek()!='let': return self.finish(self.expr())
        self.take('let');steps=[];names=set()
        while True:
            name=self.name();self.take('=')
            if name in names: raise LanguageError('Duplicate M binding')
            names.add(name);steps.append((name,self.expr()))
            if self.peek()!=',': break
            self.take(',')
        self.take('in');return self.finish(('let',steps,self.expr()))
    def expr(self,minimum=0):
        token=self.peek()
        if token=='if':
            self.take();condition=self.expr();self.take('then');yes=self.expr();self.take('else');node=('if',condition,yes,self.expr())
        elif token=='each': self.take();node=('each',self.expr())
        elif token=='(':
            self.take();node=self.expr();self.take(')')
        elif token=='[':
            self.take();name=self.name()
            if self.peek()=='=':
                self.take();entries=[(name,self.expr())]
                while self.peek()==',':
                    self.take();key=self.name();self.take('=');entries.append((key,self.expr()))
                if len({k for k,v in entries})!=len(entries): raise LanguageError('Duplicate M record key')
                node=('record',entries)
            else: node=('row',name)
            self.take(']')
        elif token=='{':
            self.take();items=[]
            if self.peek()!='}':
                items.append(self.expr())
                while self.peek()==',': self.take();items.append(self.expr())
            self.take('}');node=('list',items)
        elif token=='type':
            self.take();kind=self.name()
            if kind=='table':
                self.take('[');name=self.name();self.take('=');dtype=self.name();self.take(']');node=('type_table',name,dtype)
            elif kind=='date': node=('literal','date')
            else: raise LanguageError('Unsupported M type')
        elif token.startswith('"'):
            self.take();value=token[1:-1].replace('""','"')
            value=value.replace('#(lf)','\n').replace('#(cr)','\r').replace('#(tab)','\t')
            if '#(' in value: raise LanguageError('Unsupported M escape')
            node=('literal',value)
        elif token.isdigit(): self.take();node=('literal',int(token))
        elif token in ('null','true','false'): self.take();node=('literal',{'null':None,'true':True,'false':False}[token])
        else:
            name=self.name();node=('name',name)
            if self.peek()=='(':
                self.take();args=[]
                if self.peek()!=')':
                    args.append(self.expr())
                    while self.peek()==',': self.take();args.append(self.expr())
                self.take(')');node=('call',name,args)
        while self.peek() in ('[','{'):
            if self.peek()=='[': self.take();name=self.name();self.take(']');node=('field',node,name)
            else: self.take();selector=self.expr();self.take('}');node=('navigate',node,selector)
        precedence={'=':1,'+':2,'-':2,'*':3}
        while self.peek() in precedence and precedence[self.peek()]>=minimum:
            op=self.take();node=('binary',op,node,self.expr(precedence[op]+1))
        return node


def evaluate_m(text, query):
    tree=MParser(text).parse();trace=[]
    def value(node,env,row=None):
        kind=node[0]
        if kind=='literal': return node[1]
        if kind=='type_table':
            if node[2]!='Int64.Type': raise LanguageError('Unsupported table type')
            return ('schema',node[1])
        if kind=='name':
            if node[1]=='Int64.Type': return 'int64'
            if node[1] not in env: raise LanguageError('Unbound M reference: '+node[1])
            return env[node[1]]
        if kind=='let':
            bindings=dict(env)
            for name,expression in node[1]: bindings[name]=value(expression,bindings);trace.append({'binding':name,'rows':len(bindings[name]) if isinstance(bindings[name],list) else None})
            return value(node[2],bindings)
        if kind=='row':
            if row is None or node[1] not in row: raise LanguageError('Unbound M row field: '+node[1])
            return row[node[1]]
        if kind=='record': return {k:value(v,env,row) for k,v in node[1]}
        if kind=='list': return [value(v,env,row) for v in node[1]]
        if kind=='each': return ('lambda',node[1],dict(env))
        if kind=='if':
            condition=value(node[1],env,row)
            if type(condition) is not bool: raise LanguageError('M if condition must be logical')
            return value(node[2] if condition else node[3],env,row)
        if kind=='binary':
            left=value(node[2],env,row);right=value(node[3],env,row)
            if node[1]=='=': return left==right
            if left is None or right is None: return None
            if type(left) is not int or type(right) is not int: raise LanguageError('M integer arithmetic required')
            return {'+':lambda:left+right,'-':lambda:left-right,'*':lambda:left*right}[node[1]]()
        if kind=='navigate':
            source=value(node[1],env,row);selector=value(node[2],env,row)
            if source!=('snowflake','DMA_POWERBI_SYNTHETIC','SYNTHETIC_LOCAL_ONLY') or selector!={'Name':'DMA_POWERBI','Kind':'Database'}: raise LanguageError('M source account/database binding mismatch')
            return {'Data':('database','DMA_POWERBI')}
        if kind=='field':
            source=value(node[1],env,row)
            if source!={'Data':('database','DMA_POWERBI')} or node[2]!='Data': raise LanguageError('Unsupported M navigation field')
            return source['Data']
        if kind!='call': raise LanguageError('Unsupported M expression')
        function=node[1];args=[value(a,env,row) for a in node[2]]
        if function=='Snowflake.Databases' and len(args)==2:
            if args!=['DMA_POWERBI_SYNTHETIC','SYNTHETIC_LOCAL_ONLY']: raise LanguageError('M source account/warehouse mismatch')
            return ('snowflake',*args)
        if function=='Value.NativeQuery' and len(args)==4:
            if args[0]!=('database','DMA_POWERBI') or not isinstance(args[1],str) or args[2] is not None or args[3]!={'EnableFolding':True}: raise LanguageError('Unsupported M native query contract')
            records,sql=query(args[1]);trace.append({'native_sql':args[1],'local_sql':sql,'rows':len(records),'native_connector_executed':False})
            return [{k.upper():v for k,v in r.items()} for r in records]
        if function=='Table.AddColumn' and len(args)==4:
            records,name,callback,dtype=args
            if not isinstance(records,list) or not isinstance(name,str) or not isinstance(callback,tuple) or callback[0]!='lambda' or dtype not in ('int64','date'): raise LanguageError('Unsupported M AddColumn contract')
            output=[]
            for record in records:
                if name in record: raise LanguageError('M AddColumn overwrites existing field')
                cell=value(callback[1],callback[2],record)
                if cell is not None and ((dtype=='int64' and type(cell) is not int) or (dtype=='date' and (not isinstance(cell,str) or date.fromisoformat(cell).isoformat()!=cell))): raise LanguageError('M result type mismatch')
                output.append(dict(record,**{name:cell}))
            return output
        if function=='Date.StartOfMonth' and len(args)==1:
            return date.fromisoformat(args[0]).replace(day=1).isoformat() if args[0] is not None else None
        if function=='#table' and len(args)==2:
            schema,records=args
            if schema!=('schema','MULTIPLIER') or records!=[[1],[2]]: raise LanguageError('Unsupported Scenario table/domain')
            return [{'MULTIPLIER':r[0]} for r in records]
        raise LanguageError('Unsupported M function: '+function)
    result=value(tree,{})
    if not isinstance(result,list) or any(not isinstance(r,dict) for r in result): raise LanguageError('M partition must return table')
    return result,trace


DAX_TOKEN=re.compile(r'\s*(\'(?:[^\']|\'\')*\'|"(?:[^"]|"")*"|\[(?:[^\]]|\]\])*\]|[A-Za-z_][A-Za-z_0-9]*|\d+|[(),=*+-])')


class DAXParser(Tokens):
    def __init__(self,text): super().__init__(text,DAX_TOKEN)
    def parse(self): return self.finish(self.expr())
    def expr(self,minimum=0):
        token=self.take()
        if token=='(':
            node=self.expr();self.take(')')
        elif token.startswith('"'): node=('literal',token[1:-1].replace('""','"'))
        elif token.isdigit(): node=('literal',int(token))
        elif token.startswith('['): node=('measure',token[1:-1].replace(']]',']'))
        elif self.peek().startswith('['):
            column=self.take()[1:-1].replace(']]',']');table=token[1:-1].replace("''", "'") if token.startswith("'") else token
            node=('column',table,column)
        elif self.peek()=='(':
            self.take();args=[]
            if self.peek()!=')':
                args.append(self.expr())
                while self.peek()==',': self.take();args.append(self.expr())
            self.take(')');node=('call',token.upper(),args)
        else: raise LanguageError('Unsupported DAX expression: '+token)
        precedence={'=':1,'+':2,'-':2,'*':3}
        while self.peek() in precedence and precedence[self.peek()]>=minimum:
            op=self.take();node=('binary',op,node,self.expr(precedence[op]+1))
        return node


def safe_divide(left,right):
    if left is None or right is None or right==0: return None
    with localcontext() as context:
        context.prec=50
        return Decimal(left)/Decimal(right)


class DAXSubset:
    """Evaluate measure context over joined, security-filtered source rows.

Ordinary column restrictions live in context. Security is already applied to
both source tables, and cannot be modified by CALCULATE/REMOVEFILTERS.
"""
    def __init__(self, rows, measures, scenario_values):
        self.rows=rows;self.measures={k:DAXParser(v).parse() for k,v in measures.items()};self.scenario_values=scenario_values;self.executed=set()
    def selected(self,context):
        return [r for r in self.rows if all(key in r and (r[key] in values if isinstance(values,set) else values[0]<=r[key]<values[1]) for key,values in context.items())]
    def measure(self,name,context,stack=()):
        if name not in self.measures or name in stack: raise LanguageError('Missing/cyclic DAX measure: '+name)
        self.executed.add(name);return self.value(self.measures[name],context,None,stack+(name,))
    def value(self,node,context,row=None,stack=()):
        kind=node[0]
        if kind=='literal': return node[1]
        if kind=='column':
            key=(node[1],node[2])
            if row is None or key not in row: raise LanguageError('DAX column requires supported row context')
            return row[key]
        if kind=='measure':
            if row is not None: raise LanguageError('Automatic row-context transition is unsupported')
            return self.measure(node[1],context,stack)
        if kind=='binary':
            left=self.value(node[2],context,row,stack);right=self.value(node[3],context,row,stack)
            if node[1]=='=': return left==right
            # Only multiplication/subtraction used by this fixture. DAX BLANK
            # addition/subtraction coercion differs from null SQL arithmetic.
            if node[1]=='*': return None if left is None or right is None else left*right
            if left is None and right is None: return None
            if node[1]=='+': return (left or 0)+(right or 0)
            return (left or 0)-(right or 0)
        if kind!='call': raise LanguageError('Unsupported DAX AST')
        function,args=node[1:]
        if function=='SUM' and len(args)==1 and args[0][0]=='column':
            key=tuple(args[0][1:]);records=self.selected(context)
            if any(key not in r for r in self.rows): raise LanguageError('Unbound SUM column')
            values=[r[key] for r in records if r[key] is not None]
            return sum(values) if values else None
        if function=='DIVIDE' and len(args) in (2,3):
            left=self.value(args[0],context,row,stack);right=self.value(args[1],context,row,stack)
            return (self.value(args[2],context,row,stack) if len(args)==3 else None) if right is None or right==0 else safe_divide(left,right)
        if function=='SELECTEDVALUE' and len(args)==2 and args[0]==('column','Scenario','Multiplier'):
            values=self.scenario_values
            return values[0] if len(values)==1 else self.value(args[1],context,row,stack)
        if function=='CALCULATE' and len(args)==2 and row is None:
            changed=dict(context);modifier=args[1];keep=False
            if modifier[0]=='call' and modifier[1]=='REMOVEFILTERS' and len(modifier[2])==1 and modifier[2][0][0]=='column':
                key=tuple(modifier[2][0][1:])
                if key!=('Customers','Segment'): raise LanguageError('Unqualified REMOVEFILTERS scope')
                changed.pop(key,None)
            else:
                if modifier[0]=='call' and modifier[1]=='KEEPFILTERS' and len(modifier[2])==1: keep=True;modifier=modifier[2][0]
                if modifier[0:2]!=('binary','=') or modifier[2][0]!='column' or modifier[3][0]!='literal': raise LanguageError('Unsupported CALCULATE filter')
                key=tuple(modifier[2][1:]);values={modifier[3][1]}
                if key!=('Invoices','Status'): raise LanguageError('Unqualified CALCULATE column')
                if keep and key in changed: values=values & changed[key]
                changed[key]=values
            return self.value(args[0],changed,None,stack)
        raise LanguageError('Unsupported DAX function: '+function)
